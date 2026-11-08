"""Remove a project from creation surfaces while retaining its settlement graph."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from services.creation_objects import project_write
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

    async with project_write(project.id) as connection:
        tasks = await project_tasks(project.id)
        # Internal model steps finish their own accounting after the parent stops.
        for task in tasks:
            if task.status in ACTIVE and not (task.request_params or {}).get('parent_task_id'):
                try:
                    await cancel_task(task.id)
                except HTTPException as error:
                    latest = await AiTask.get_or_none(id=task.id)
                    if error.status_code != 400 or latest is None or latest.status in ACTIVE:
                        raise
        ids = [task.id for task in tasks]
        uncertain_ids = await AgentOperation.filter(task_id__in=ids, external=True, state='uncertain').values_list('task_id', flat=True)
        await AiTask.filter(id__in=uncertain_ids, status=TaskStatusEnum.cancelled.value).update(
            status=TaskStatusEnum.failed.value, stage='needs_review')
        deleted_at = datetime.now(timezone.utc)
        for task in await AiTask.filter(id__in=ids):
            params = dict(task.request_params or {})
            params['deleted_project'] = {'id': project.id, 'name': project.name, 'deleted_at': deleted_at.isoformat()}
            # Legacy chapter-only tasks must retain their original billing scope.
            params.setdefault('novel_id', project.id)
            await AiTask.filter(id=task.id).update(request_params=params)
        # Keep FK targets for late usage/callbacks; active queries hide this tombstone.
        # Release the title without changing the existing ownership/name index.
        await Novel.filter(id=project.id).using_db(connection).update(
            deleted_at=deleted_at, name=f'deleted:{project.id}:{uuid4().hex}',
            content=None, description=None, story_outline=None, project_setting=None,
            storyboard_setting=None, custom_style_prompt=None, cover=None, updated_at=deleted_at,
        )
