"""Chapter composition uses the same durable production task lifecycle."""

from models.chapter import Chapter
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from services.creation_objects import project_write as creation_write
from services.creation_agent.operation_receipts import execute_step
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def resume_local_composition(task, connection):
    """Explicit download retries may resume this deterministic step, never paid media."""
    if (task.task_type != AiTaskTypeEnum.video.value
        or task.request_params.get('operation') != 'compose'
        or task.request_params.get('workflow_version') != 'agent-skills-v1'
        or task.status != TaskStatusEnum.failed.value
        or task.stage not in {'failed', 'needs_review'}):
        return task
    row = await AgentOperation.get_or_none(task=task, key='media:compose').using_db(connection)
    if row is None or row.state not in {'running', 'uncertain', 'failed'}:
        return task
    if await AgentOperation.filter(task=task, external=True).exclude(key='media:compose').using_db(connection).exists():
        return task
    audit = {'previous_stage': task.stage, 'previous_step_state': row.state, 'previous_external': row.external}
    await AgentOperation.filter(id=row.id).using_db(connection).update(external=False, state='pending')
    await AiTask.filter(id=task.id).using_db(connection).update(status=TaskStatusEnum.queued.value,
        stage='resuming', error_message=None, started_at=None, finished_at=None,
        request_params={**task.request_params, 'composition_recovery': task.request_params.get('composition_recovery') or audit})
    await task.refresh_from_db(using_db=connection)
    return task


async def submit_composition(chapter_id, *, strict=False, team_id=None, user_id=None):
    from services.ai_task_executor import ai_task_executor

    chapter = await Chapter.get(id=chapter_id)
    from services.creation_agent.skill_execution import prepare_workflow

    params = await prepare_workflow(
        {
            "operation": "compose",
            "chapter_id": chapter_id,
            "novel_id": chapter.novel_id,
            "strict": strict,
            "team_id": team_id,
            "user_id": user_id,
        }
    )
    async with creation_write(chapter.novel_id) as connection:
        from services.creation_agent.submissions import (
            previous_submission,
            bind_submission,
        )

        previous = await previous_submission(4, params, connection)
        if previous:
            return await resume_local_composition(previous, connection)
        for task in await AiTask.filter(
            task_type=AiTaskTypeEnum.video.value, status__in=[1, 2, 6]
        ).using_db(connection):
            if (
                task.request_params.get("operation") == "compose"
                and task.request_params.get("chapter_id") == chapter_id
            ):
                return await bind_submission(task, params)
        return await ai_task_executor.submit(
            AiTaskTypeEnum.video, params, db_connection=connection
        )


class CompositionHandler:
    def timeout_seconds(self, params):
        return 1200

    async def execute(self, params):
        from controllers.video import video_controller

        async def compose():
            return await video_controller._compose_chapter(
                params["chapter_id"], strict=params.get("strict", False)
            )

        return await execute_step(
            params["task_id"], "media:compose", compose
        )
