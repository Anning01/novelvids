"""Shared cooperative task cancellation; submitted requests retain their settlement path."""
from uuid import UUID
from datetime import datetime, timezone
from fastapi import HTTPException
from models.ai_task import AiTask
from services.task_signals import task_signals
from utils.enums import TaskStatusEnum
from utils.messages import localized_message


async def cancel_task(task_id: UUID) -> AiTask:
    task = await AiTask.get_or_none(id=task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="AiTask not found")
    if task.status not in (
        TaskStatusEnum.pending.value,
        TaskStatusEnum.running.value,
        TaskStatusEnum.queued.value,
    ):
        raise HTTPException(
            status_code=400,
            detail=localized_message('当前状态({p1})不可取消', p1=localized_message(TaskStatusEnum(task.status).nickname)),
        )
    await AiTask.filter(id=task.id, status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value, TaskStatusEnum.queued.value]).update(
        status=TaskStatusEnum.cancelled.value, finished_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    await task.refresh_from_db()
    await task_signals.publish(str(task.id))
    if task.request_params.get('workflow_version') == 'agent-skills-v1':
        children = [child for child in await AiTask.filter(status__in=[1, 2, 6])
                    if child.request_params.get('origin_run_id') == str(task.id)]
        for child in children:
            await cancel_task(child.id)
        if task.request_params.get('operation') == 'video':
            from models.video import Video
            video = await Video.get_or_none(id=task.request_params.get('video_id'))
            # Never mark an in-flight provider submission as cancelled locally.
            if video and video.status == TaskStatusEnum.queued.value:
                await Video.filter(id=video.id, status=TaskStatusEnum.queued.value).update(status=TaskStatusEnum.cancelled.value)
        from services.creation_agent.production import finish_production_message
        await finish_production_message(task)
    return task
