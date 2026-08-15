from utils.crud import CRUDBase
from models.scene import Scene
from pydantic import BaseModel

from schemas.scene import SceneCreate, SceneUpdate
from models.asset import Asset
from models.chapter import Chapter
from models.ai_task import AiTask
from controllers.config import ai_model_config_controller
from services.ai_task_executor import ai_task_executor
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from fastapi import HTTPException
from tortoise.transactions import in_transaction


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

    async def generate(self, chapter_id: int):
        """提交分镜生成任务，返回任务记录供前端轮询。"""

        chapter = await Chapter.get(id=chapter_id)

        # 1. 获取分镜生成任务的启用配置
        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.storyboard.value
        )

        # 2. 先清理超时异常任务，再检查是否有活跃任务
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.storyboard)

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.storyboard.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for t in active_tasks:
            if t.request_params.get("chapter_id") == chapter_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"该章节已有进行中的分镜生成任务（{t.id}）",
                )

        # 3. 提交任务（BackgroundTask 中执行）
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
        }
        task = await ai_task_executor.submit(
            AiTaskTypeEnum.storyboard, request_params
        )
        return task


scene_controller = SceneController()
