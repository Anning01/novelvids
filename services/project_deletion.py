"""Stop future project work and keep settlement evidence until deletion is safe."""
from fastapi import HTTPException

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.asset import Asset
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.creation_agent import AgentMessage
from models.scene import Scene
from models.video import Video
from services.creation_objects import project_write
from utils.messages import localized_message as msg
from utils.enums import TaskStatusEnum

ACTIVE = {TaskStatusEnum.pending.value, TaskStatusEnum.running.value, TaskStatusEnum.queued.value}


async def project_tasks(novel_id: int) -> list[AiTask]:
    chapters = set(await Chapter.filter(novel_id=novel_id).values_list('id', flat=True))
    scenes = set(await Scene.with_deleted().filter(chapter_id__in=chapters).values_list('id', flat=True))
    assets = set(await Asset.with_deleted().filter(novel_id=novel_id).values_list('id', flat=True))
    all_tasks = await AiTask.all()
    related = {task.id: task for task in all_tasks if (
        str((task.request_params or {}).get('novel_id')) == str(novel_id)
        or (task.request_params or {}).get('chapter_id') in chapters
        or (task.request_params or {}).get('scene_id') in scenes
        or (task.request_params or {}).get('asset_id') in assets
    )}
    while True:
        ids = {str(key) for key in related}
        children = [task for task in all_tasks if task.id not in related and any(
            str((task.request_params or {}).get(key)) in ids for key in ('parent_task_id', 'origin_run_id'))]
        if not children:
            return list(related.values())
        related.update({task.id: task for task in children})


async def remove_project(project) -> None:
    from services.task_cancellation import cancel_task
    from services.ai_task_executor import ai_task_executor

    blocked = False
    async with project_write(project.id) as connection:
        tasks = await project_tasks(project.id)
        # Internal model steps settle through their parent; do not cancel their accounting.
        for task in tasks:
            params = task.request_params or {}
            if task.status in ACTIVE and not params.get('parent_task_id'):
                try:
                    await cancel_task(task.id)
                except HTTPException as error:
                    latest = await AiTask.get_or_none(id=task.id)
                    if error.status_code != 400 or latest is None or latest.status in ACTIVE:
                        raise
                    # Parent cancellation or an arriving response already closed this task.
        ids = [task.id for task in tasks]
        uncertain_ids = await AgentOperation.filter(task_id__in=ids, external=True, state='uncertain').values_list('task_id', flat=True)
        await AiTask.filter(id__in=uncertain_ids, status=TaskStatusEnum.cancelled.value).update(
            status=TaskStatusEnum.failed.value, stage='needs_review')
        current = await AiTask.filter(id__in=ids)
        blocked = any(task.status in ACTIVE or task.stage in {'needs_review', 'billing_pending'}
                      or (task.request_params or {}).get('billing_pending')
                      or (task.started_at is not None and ai_task_executor.is_executing(task.id)) for task in current)
        blocked = blocked or await AgentOperation.filter(task_id__in=ids, external=True, state__in=['running', 'uncertain']).exists()
        for message in await AgentMessage.filter(task_id__in=ids, role='assistant'):
            if (message.usage or {}).get('calls') and (message.billing_record_id is None or message.billing_record_id == -1):
                blocked = True
        chapter_ids = await Chapter.filter(novel_id=project.id).values_list('id', flat=True)
        scene_ids = await Scene.with_deleted().filter(chapter_id__in=chapter_ids).values_list('id', flat=True)
        videos = await Video.filter(scene_id__in=scene_ids)
        blocked = blocked or any(row.status in ACTIVE or (row.metadata or {}).get('billing_pending') for row in videos)
        exports = await ChapterExport.filter(novel_id=project.id, collection_complete=False)
        blocked = blocked or any(row.provider_task_id or row.submission_slot for row in exports)
        if not blocked:
            await project.delete(using_db=connection)
    # Commit cancellation even when physical deletion must wait for provider/usage settlement.
    if blocked:
        raise HTTPException(409, msg('已停止未提交的后续步骤，模型请求或费用仍在收尾或待核对，请完成后再删除。已发生费用不会退款。'))
