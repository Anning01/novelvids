"""Explicit human closure of uncertain external requests; never replays a step."""

from datetime import datetime, timezone
from fastapi import HTTPException
from tortoise.expressions import Q
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.video import Video
from models.usage_record import ModelUsageRecord
from services.creation_objects import project_write
from utils.messages import localized_message


def review_certainty(outcome, records):
    # A failed or unrecoverable provider result does not verify its usage. An
    # existing explicitly verified ledger can retain that independent knowledge.
    usage_known = (
        outcome == "not_submitted"
        or bool(records)
        and all(
            record.usage.get("usage_known") is True
            and not record.usage.get("missing_usage")
            for record in records
        )
    )
    return {
        "submission_outcome_known": True,
        "media_result_recoverable": False
        if outcome == "completed_unrecoverable"
        else None,
        "usage_known": usage_known,
        "missing_usage": not usage_known,
        # Compatibility flag for unresolved submission/accounting, kept in sync
        # with the ledger; retry decisions use the explicit outcome state.
        "submission_uncertain": not usage_known,
    }


async def close_uncertain_task(task_id, resolution, *, user_id=None):
    task = await AiTask.get(id=task_id)
    async with project_write(task.request_params["novel_id"]) as connection:
        task = (
            await AiTask.filter(id=task.id)
            .using_db(connection)
            .select_for_update()
            .get()
        )
        existing = await AgentOperation.get_or_none(task=task, key="review:closure")
        if existing:
            if (
                existing.result.get("outcome") != resolution.outcome
                or existing.result.get("note") != resolution.note
            ):
                raise HTTPException(
                    409, localized_message("同一请求标识不能对应不同内容")
                )
        elif task.status != 4 or task.stage != "needs_review":
            raise HTTPException(
                409, localized_message("只有待核对的失败任务可以人工收口")
            )
        video = await Video.get_or_none(id=task.request_params.get("video_id"))
        if video and video.external_task_id:
            raise HTTPException(
                409, localized_message("已有供应商任务号，请先查询真实结果")
            )
        related = Q(ai_task_id=task.id)
        if video:
            related |= Q(video_id=video.id)
        records = (
            await ModelUsageRecord.filter(related, billing_type__in=["image", "video"])
            .using_db(connection)
            .select_for_update()
        )
        certainty = review_certainty(resolution.outcome, records)
        audit = {
            **(
                existing.result
                if existing
                else {
                    "outcome": resolution.outcome,
                    "note": resolution.note,
                    "user_id": user_id,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "automatic_retry": False,
                }
            ),
            "certainty": certainty,
        }
        if existing:
            existing.result = audit
            await existing.save(update_fields=["result"])
        else:
            await AgentOperation.create(
                task=task, key="review:closure", state="completed", result=audit
            )
        # The original external receipt stays uncertain and cannot be claimed
        # again. Closure reconciles flags, never quantities, prices or charges.
        task.stage = "review_closed"
        task.request_params = {**task.request_params, "review_certainty": certainty}
        await task.save(update_fields=["stage", "request_params", "updated_at"])
        for record in records:
            record.usage = {**record.usage, **certainty}
            await record.save(update_fields=["usage"])
        if video:
            video.status = 4
            video.metadata = {
                **(video.metadata or {}),
                **certainty,
                "review_resolution": audit,
            }
            await video.save(update_fields=["status", "metadata", "updated_at"])
        return task
