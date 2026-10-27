"""Explicit human closure of uncertain external requests; never replays a step."""

from datetime import datetime, timezone
from dataclasses import asdict
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
        "media_result_recoverable": {
            "completed_unrecoverable": False,
            "completed": True,
        }.get(outcome),
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
        evidence = None
        key = (
            "review:recheck:" + resolution.evidence_id
            if resolution.evidence_id
            else "review:closure"
        )
        existing = await AgentOperation.get_or_none(task=task, key=key)
        if existing:
            if (
                existing.result.get("outcome") != resolution.outcome
                or existing.result.get("note") != resolution.note
            ):
                raise HTTPException(
                    409, localized_message("同一请求标识不能对应不同内容")
                )
            # The original finding is immutable once newer provider evidence
            # arrives. Replaying an old request cannot clear the conflict.
            if resolution.evidence_id or task.request_params.get("review_evidence"):
                return task
        elif task.status != 4 or task.stage != "needs_review":
            raise HTTPException(
                409, localized_message("只有待核对的失败任务可以人工收口")
            )
        if resolution.evidence_id:
            from services.creation_agent.review_evidence import (
                MediaEvidence,
                outcome_conflicts,
            )

            if (task.request_params.get("review_evidence") or {}).get(
                "id"
            ) != resolution.evidence_id:
                raise HTTPException(
                    409, localized_message("迟到证据已变化，请核对最新证据")
                )
            event = await AgentOperation.get_or_none(
                task=task,
                key="review:evidence:" + resolution.evidence_id,
                state="completed",
            )
            if event is None:
                raise HTTPException(
                    409, localized_message("迟到证据已变化，请核对最新证据")
                )
            evidence = MediaEvidence(**event.result["evidence"])
            if outcome_conflicts(resolution.outcome, evidence):
                raise HTTPException(409, localized_message("核对结论与供应商证据矛盾"))
        video = await Video.get_or_none(id=task.request_params.get("video_id"))
        if (
            video
            and video.external_task_id
            and (evidence is None or video.status not in {3, 4, 5})
        ):
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
        if evidence is None:
            from services.creation_agent.review_evidence import (
                MediaEvidence,
                outcome_conflicts,
            )

            for record in records:
                facts = record.usage.get("provider_evidence")
                if facts:
                    proof = MediaEvidence(**facts)
                    if outcome_conflicts(resolution.outcome, proof):
                        raise HTTPException(
                            409, localized_message("核对结论与供应商证据矛盾")
                        )
                    evidence = proof
        if resolution.outcome == "completed" and (
            evidence is None or evidence.media_available is not True
        ):
            raise HTTPException(
                409, localized_message("确认完成需要可恢复的实际媒体证据")
            )
        certainty = review_certainty(resolution.outcome, records)
        if evidence:
            from services.creation_agent.review_evidence import (
                evidence_certainty,
                quantity,
            )

            field = "image_count" if evidence.kind == "image" else "seconds"
            accounting_pending = evidence.quantity is not None and any(
                quantity(record.usage.get(field)) not in {None, evidence.quantity}
                for record in records
            )
            certainty = evidence_certainty(
                certainty, evidence, accounting_pending=accounting_pending
            )
            certainty["submission_outcome_known"] = True

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
        if evidence:
            audit["accepted_evidence"] = asdict(evidence)
        if existing:
            existing.result = audit
            await existing.save(update_fields=["result"])
        else:
            await AgentOperation.create(
                task=task, key=key, state="completed", result=audit
            )
        # The original external receipt stays uncertain and cannot be claimed
        # again. Closure reconciles flags, never quantities, prices or charges.
        task.stage = "review_closed"
        task.request_params = {
            **task.request_params,
            "review_certainty": certainty,
            "review_conflict": False,
            "review_resolution_key": key,
        }
        await task.save(update_fields=["stage", "request_params", "updated_at"])
        for record in records:
            record.usage = {**record.usage, **certainty}
            await record.save(update_fields=["usage"])
        if video:
            video.status = 3 if resolution.outcome == "completed" else 4
            video.metadata = {
                **(video.metadata or {}),
                **certainty,
                (
                    "latest_review_resolution"
                    if resolution.evidence_id
                    else "review_resolution"
                ): audit,
            }
            await video.save(update_fields=["status", "metadata", "updated_at"])
        return task
