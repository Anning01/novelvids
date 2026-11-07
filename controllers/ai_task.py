
from uuid import UUID

from fastapi import HTTPException

from models.ai_task import AiTask


class AiTaskController:
    """AI 任务控制器 - 仅对外暴露查询和取消。"""

    async def get(self, task_id: UUID) -> AiTask:
        task = await AiTask.get_or_none(id=task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="AiTask not found")
        return task

    async def cancel(self, task_id: UUID) -> AiTask:
        from services.task_cancellation import cancel_task
        return await cancel_task(task_id)


ai_task_controller = AiTaskController()
