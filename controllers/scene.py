from utils.crud import CRUDBase
from models.scene import Scene
from schemas.scene import SceneCreate, SceneUpdate


class SceneController(CRUDBase[Scene, SceneCreate, SceneUpdate]):
    def __init__(self):
        super().__init__(model=Scene)

    async def update(self, ncene_id: int, obj_in: SceneUpdate) -> Scene:
        instance = await self.get(ncene_id)
        return await super().update(instance, obj_in)

    async def patch(self, ncene_id: int, obj_in: SceneUpdate) -> Scene:
        instance = await self.get(ncene_id)
        return await super().patch(instance, obj_in)

    async def remove(self, ncene_id: int) -> None:
        instance = await self.get(ncene_id)
        await super().remove(instance)

    async def create(self, chapter_id: int):
        """提交分镜生成任务，返回任务记录供前端轮询。"""
        from models import Chapter, AiTask
        from controllers.ai_model_config import ai_model_config_controller
        from services.ai_task_executor import ai_task_executor
        from utils.enums import AiTaskTypeEnum, TaskStatusEnum
        from fastapi import HTTPException

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
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
        }
        task = await ai_task_executor.submit(
            AiTaskTypeEnum.storyboard, request_params
        )
        return task


scene_controller = SceneController()
