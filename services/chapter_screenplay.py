"""Generate a single director's screenplay from its preserved source."""
from fastapi import HTTPException
from pydantic import BaseModel, Field

from models.ai_task import AiTask
from models.chapter import Chapter
from services.ai_task_executor import BaseTaskHandler, ai_task_executor
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.skill_execution import current_execution, prepare_workflow
from services.creation_objects import ACTIVE_TASK_STATUSES, project_write
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message


class EpisodeScript(BaseModel):
    screenplay: str = Field(min_length=1, description="可直接交给演员和制作团队的完整分场导演剧本")


async def submit_screenplay(chapter_id, ctx):
    chapter = await Chapter.get_or_none(id=chapter_id)
    if chapter is None:
        raise HTTPException(404, localized_message("章节不存在"))
    params = {"novel_id": chapter.novel_id, "chapter_id": chapter_id, "operation": "screenplay",
              "team_id": ctx.team_id, "user_id": ctx.user.id if ctx.user else None}
    params = await prepare_workflow(params)
    async with project_write(chapter.novel_id) as db:
        await chapter.refresh_from_db(using_db=db)
        if chapter.screenplay or not (chapter.content or "").strip():
            raise HTTPException(409, localized_message("本集已有导演剧本或缺少原文"))
        for task in await AiTask.filter(task_type=AiTaskTypeEnum.screenplay, status__in=ACTIVE_TASK_STATUSES).using_db(db):
            if task.request_params.get("chapter_id") == chapter_id:
                return task
        params["source_version"] = fingerprint([chapter.name, chapter.content])
        return await ai_task_executor.submit(AiTaskTypeEnum.screenplay, params, db_connection=db)


class ScreenplayHandler(BaseTaskHandler):
    async def execute(self, params):
        execution = current_execution.get()
        chapter = await Chapter.get(id=params["chapter_id"], novel_id=params["novel_id"])

        def verify_source():
            if chapter.screenplay or fingerprint([chapter.name, chapter.content]) != params["source_version"]:
                raise ValueError(localized_message("本集原文或剧本已修改，请刷新后查看"))

        from models.agent_operation import AgentOperation
        receipt = await AgentOperation.get_or_none(task_id=params["task_id"], key="persist:screenplay", state="completed")
        if receipt:
            return receipt.result
        verify_source()
        draft = await execution.generate("screenplay", {"episode_number": chapter.number,
            "episode_name": chapter.name, "source_text": chapter.content}, EpisodeScript)
        if not draft.screenplay.strip():
            raise ValueError(localized_message("模型未返回导演剧本"))

        async def save():
            async with project_write(chapter.novel_id) as db:
                await execution.before_request()
                await chapter.refresh_from_db(using_db=db)
                verify_source()
                chapter.screenplay = draft.screenplay
                await chapter.save(using_db=db, update_fields=["screenplay", "updated_at"])
                return {"chapter_id": chapter.id, "screenplay_saved": True}

        return await execute_step(params["task_id"], "persist:screenplay", save, atomic=True)
