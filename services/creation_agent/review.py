"""Explicit human closure of uncertain external requests; never replays a step."""

from datetime import datetime, timezone
from fastapi import HTTPException
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.video import Video
from services.creation_objects import project_write
from utils.messages import localized_message


async def close_uncertain_task(task_id, resolution, *, user_id=None):
    task = await AiTask.get(id=task_id)
    async with project_write(task.request_params["novel_id"]):
        await task.refresh_from_db()
        existing = await AgentOperation.get_or_none(task=task, key="review:closure")
        if existing:
            if (
                existing.result.get("outcome") != resolution.outcome
                or existing.result.get("note") != resolution.note
            ):
                raise HTTPException(
                    409, localized_message("同一请求标识不能对应不同内容")
                )
            return task
        if task.status != 4 or task.stage != "needs_review":
            raise HTTPException(
                409, localized_message("只有待核对的失败任务可以人工收口")
            )
        video = await Video.get_or_none(id=task.request_params.get("video_id"))
        if video and video.external_task_id:
            raise HTTPException(
                409, localized_message("已有供应商任务号，请先查询真实结果")
            )
        audit = {
            "outcome": resolution.outcome,
            "note": resolution.note,
            "user_id": user_id,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "automatic_retry": False,
        }
        await AgentOperation.create(
            task=task, key="review:closure", state="completed", result=audit
        )
        # The original uncertain receipt stays intact. It can never be claimed
        # again, even if someone later attempts to requeue this task.
        task.stage = "review_closed"
        await task.save(update_fields=["stage", "updated_at"])
        if video:
            video.status = 4
            video.metadata = {
                **(video.metadata or {}),
                "submission_uncertain": False,
                "review_resolution": audit,
            }
            await video.save(update_fields=["status", "metadata", "updated_at"])
        return task
