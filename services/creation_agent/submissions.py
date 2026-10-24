"""A client retry reuses a server task even after the first response was lost."""

from utils.messages import localized_message
from contextvars import ContextVar
from fastapi import HTTPException
from models.ai_task import AiTask

submission: ContextVar[dict | None] = ContextVar("production_submission", default=None)


async def previous_submission(task_type, params, connection=None):
    request_id = params.get("submission_id")
    if not request_id:
        return None
    rows = await AiTask.filter(task_type=task_type).using_db(connection)
    for row in rows:
        saved = row.request_params
        if saved.get("submission_id") != request_id:
            continue
        if any(
            saved.get(key) != params.get(key)
            for key in ("team_id", "user_id", "novel_id")
        ):
            continue
        if saved.get("submission_hash") != params.get("submission_hash"):
            raise HTTPException(409, localized_message("同一请求标识不能对应不同内容"))
        return row
    return None
