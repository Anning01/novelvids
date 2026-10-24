"""Chapter composition uses the same durable production task lifecycle."""

from models.chapter import Chapter
from models.ai_task import AiTask
from services.creation_objects import project_write as creation_write
from services.creation_agent.operation_receipts import execute_step
from utils.enums import AiTaskTypeEnum


async def submit_composition(chapter_id, *, strict=False, team_id=None, user_id=None):
    from services.ai_task_executor import ai_task_executor

    chapter = await Chapter.get(id=chapter_id)
    async with creation_write(chapter.novel_id) as connection:
        for task in await AiTask.filter(
            task_type=AiTaskTypeEnum.video.value, status__in=[1, 2, 6]
        ).using_db(connection):
            if (
                task.request_params.get("operation") == "compose"
                and task.request_params.get("chapter_id") == chapter_id
            ):
                return task
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
            params["task_id"], "media:compose", compose, external=True
        )
