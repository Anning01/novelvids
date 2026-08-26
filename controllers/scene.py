from utils.crud import CRUDBase
from models.scene import Scene
from pydantic import BaseModel

from schemas.scene import SceneCreate, SceneUpdate
from models.asset import Asset
from models.chapter import Chapter
from models.ai_task import AiTask
from controllers.config import ai_model_config_controller
from services.ai_task_executor import ai_task_executor
from services.storyboard.strategies import storyboard_strategy_factory
from services.oss import normalize_media_url
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from fastapi import HTTPException
from tortoise.transactions import in_transaction


def _normalize_scene_metadata(metadata: dict) -> dict:
    """写库前把首尾帧与参考素材的签名 URL 降级为 OSS key，避免过期 403。"""
    for key in ("first_frame_url", "last_frame_url"):
        raw = metadata.get(key)
        if isinstance(raw, str) and raw:
            metadata[key] = normalize_media_url(raw) or raw
    reference_media = metadata.get("video_reference_media")
    if isinstance(reference_media, list):
        for item in reference_media:
            if isinstance(item, dict):
                raw = item.get("url")
                if isinstance(raw, str) and raw:
                    item["url"] = normalize_media_url(raw) or raw
    return metadata


class SceneController(CRUDBase[Scene, SceneCreate, SceneUpdate]):
    def __init__(self):
        super().__init__(model=Scene)

    async def _get_with_assets(self, instance_id: int) -> Scene:
        """封装统一的预加载查询"""
        # 这里的 get 调用基类的 get_object_or_404
        instance = await self.get(instance_id)
        await instance.fetch_related("assets")
        return instance

    async def create(self, obj_in: SceneCreate, **kwargs) -> Scene:
        data = obj_in.model_dump(exclude_unset=True)
        asset_ids = data.pop("asset_ids", None)
        if isinstance(data.get("metadata"), dict):
            data["metadata"] = _normalize_scene_metadata(data["metadata"])
        instance = await super().create(data, **kwargs)
        if asset_ids:
            await instance.assets.add(*await Asset.filter(id__in=asset_ids))
        # 直接在当前实例上 fetch，无需重新数据库查询
        await instance.fetch_related("assets")
        return instance
    
    async def _perform_update(self, scene_id: int, obj_in: BaseModel, method: str) -> Scene:
        """
        统一处理 update 和 patch 的内部逻辑
        method: 'update' | 'patch'
        """
        instance = await self.get(scene_id)
        
        data = obj_in.model_dump(exclude_unset=True)
        asset_ids = data.pop("asset_ids", None)
        if isinstance(data.get("metadata"), dict):
            data["metadata"] = _normalize_scene_metadata(data["metadata"])

        if method == "patch":
            instance = await super().patch(instance, data)
        else:
            instance = await super().update(instance, data)

        if asset_ids is not None:
            await instance.assets.clear()
            if asset_ids:
                await instance.assets.add(*await Asset.filter(id__in=asset_ids))
            
        # 使用 fetch_related 填充已有的实例，避免重复执行 SELECT ... WHERE id = ...
        await instance.fetch_related("assets")
        return instance

    async def update(self, scene_id: int, obj_in: SceneUpdate) -> Scene:
        return await self._perform_update(scene_id, obj_in, "update")

    async def patch(self, scene_id: int, obj_in: BaseModel) -> Scene:
        return await self._perform_update(scene_id, obj_in, "patch")

    async def remove(self, scene_id: int) -> None:
        instance = await self.get(scene_id)
        await super().remove(instance)

    async def insert_after(self, scene_id: int) -> Scene:
        """在目标分镜后原子插入一个空白分镜，并保持序号连续。"""
        async with in_transaction() as connection:
            target = await Scene.filter(id=scene_id).using_db(connection).first()
            if target is None:
                raise HTTPException(status_code=404, detail="分镜不存在")

            following = await Scene.filter(
                chapter_id=target.chapter_id,
                sequence__gt=target.sequence,
            ).using_db(connection).order_by("-sequence")
            for scene in following:
                scene.sequence += 1
                await scene.save(using_db=connection, update_fields=["sequence", "updated_at"])

            created = await Scene.create(
                using_db=connection,
                chapter_id=target.chapter_id,
                sequence=target.sequence + 1,
                description="新分镜",
                prompt="",
                duration=6,
            )

        await created.fetch_related("assets")
        return created

    async def generate(
        self,
        chapter_id: int,
        team_id: int | None = None,
        user_id: int | None = None,
    ):
        """提交分镜生成任务，返回任务记录供前端轮询。

        一个章节同时只允许一个进行中的分镜拆解任务：用事务锁住章节行，
        在锁内检查活跃任务并创建，避免并发请求重复建任务浪费 token。
        """
        chapter = await Chapter.get(id=chapter_id).prefetch_related("novel")
        strategy = storyboard_strategy_factory.resolve(
            chapter.novel.storyboard_strategy
        )

        # 1. 获取分镜生成任务的启用配置（团队自定义优先，官方兜底）
        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.storyboard.value, team_id=team_id
        )

        # 2. 先清理超时异常任务
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.storyboard)

        request_params = {
            "chapter_id": chapter.id,
            "novel_id": chapter.novel_id,
            "model_config_id": config.id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "supports_json_output": config.supports_json_output,
            "max_context_characters": config.max_context_characters,
            "prompt_language": "zh",
            "storyboard_strategy": strategy.key,
        }
        if getattr(config, "thinking", None):
            request_params["thinking"] = config.thinking
        if getattr(config, "max_tokens", None):
            request_params["max_tokens"] = config.max_tokens
        if team_id is not None:
            request_params["team_id"] = team_id
        if user_id is not None:
            request_params["user_id"] = user_id

        # 3. 事务内锁章节行：检查活跃任务并创建任务保持原子性，
        #    同章节并发提交只会创建一个任务，其余请求复用同一个任务。
        async with in_transaction() as connection:
            locked_chapter = await Chapter.filter(
                id=chapter_id
            ).using_db(connection).select_for_update().first()
            if locked_chapter is None:
                raise HTTPException(status_code=404, detail="章节不存在")

            active_tasks = await AiTask.filter(
                task_type=AiTaskTypeEnum.storyboard.value,
                status__in=[
                    TaskStatusEnum.pending.value,
                    TaskStatusEnum.running.value,
                    TaskStatusEnum.queued.value,
                ],
            ).using_db(connection)
            for t in active_tasks:
                if t.request_params.get("chapter_id") == chapter_id:
                    # 已有进行中的任务：直接返回该任务，前端继续轮询，
                    # 避免离开页面再返回时重复提交被 400 拒绝
                    return t

            task = await ai_task_executor.submit(
                AiTaskTypeEnum.storyboard,
                request_params,
                db_connection=connection,
            )
        return task


scene_controller = SceneController()
