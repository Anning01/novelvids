from uuid import UUID

from fastapi import HTTPException

from models.ai_task import AiTask
from utils.enums import TaskStatusEnum


class AiTaskController:
    """AI 任务控制器 - 仅对外暴露查询和取消。"""

    async def get(self, task_id: UUID) -> AiTask:
        task = await AiTask.get_or_none(id=task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="AiTask not found")
        return task

    async def cancel(self, task_id: UUID) -> AiTask:
        task = await self.get(task_id)
        if task.status not in (
            TaskStatusEnum.pending.value,
            TaskStatusEnum.running.value,
        ):
            raise HTTPException(
                status_code=400,
                detail=f"当前状态({TaskStatusEnum(task.status).nickname})不可取消",
            )
        task.status = TaskStatusEnum.cancelled.value
        await task.save(update_fields=["status", "updated_at"])
        return task


ai_task_controller = AiTaskController()
