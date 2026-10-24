"""Append provider evidence and project certainty without rewriting human audits or money."""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from tortoise.transactions import in_transaction
from tortoise.expressions import F
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.usage_record import ModelUsageRecord
from models.video import Video


@dataclass(frozen=True)
class MediaEvidence:
    kind: str
    quantity: float | None = None
    completed: bool | None = None
    media_available: bool | None = None
    external_task_id: str | None = None

    @property
    def fingerprint(self):
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


def quantity(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def image_evidence(result, error=None):
    result = result or {}
    count = quantity(result.get("image_count"))
    images = result.get("images")
    if count is None and isinstance(images, list):
        count = float(len(images))
    if count is None:
        count = quantity(getattr(error, "image_count", None))
    if count is None:
        return None
    return MediaEvidence(
        "image", count, completed=count > 0, media_available=True if images else None
    )


def video_evidence(video):
    accounting = (video.metadata or {}).get("provider_accounting") or {}
    # Configured duration can still be used by existing pricing policy, but it
    # cannot turn an unreported supplier quantity into verified usage.
    count = (
        quantity(accounting.get("reported_seconds", accounting.get("seconds")))
        if accounting.get("usage_reported") is True
        else None
    )
    status = accounting.get("status")
    return MediaEvidence(
        "video",
        count,
        completed=True if status == 3 else False if status in {4, 5} else None,
        media_available=True if video.url else None,
        external_task_id=video.external_task_id,
    )


def outcome_conflicts(outcome, evidence):
    accepted = (
        evidence.completed is True
        or evidence.media_available is True
        or bool(evidence.external_task_id)
        or (evidence.quantity or 0) > 0
    )
    if outcome == "not_submitted" and accepted:
        return True
    if outcome == "provider_failed" and (
        evidence.completed is True or evidence.media_available is True
    ):
        return True
    if outcome == "completed_unrecoverable" and evidence.media_available is True:
        return True
    return (
        outcome in {"completed", "completed_unrecoverable"}
        and evidence.completed is False
    )


def evidence_certainty(base, evidence, *, conflict=False, accounting_pending=False):
    state = dict(base)
    known = evidence.quantity is not None or (
        bool(base.get("usage_known")) and not conflict
    )
    state.update(
        usage_known=known,
        missing_usage=not known,
        submission_outcome_known=not conflict,
        accounting_needs_review=conflict or accounting_pending,
        submission_uncertain=conflict or accounting_pending or not known,
        review_conflict=conflict,
    )
    if evidence.media_available is not None:
        state["media_result_recoverable"] = evidence.media_available
    return state


async def reconcile_evidence(task_id, record, evidence):
    if evidence is None:
        return
    task = await AiTask.get(id=task_id)
    review_key = task.request_params.get("review_resolution_key", "review:closure")
    if not await AgentOperation.filter(task_id=task.id, key=review_key).exists():
        return
    key = "review:evidence:" + evidence.fingerprint
    event, _ = await AgentOperation.get_or_create(
        task=task,
        key=key,
        defaults={
            "result": {
                "evidence": asdict(evidence),
                "usage_record_id": record.id if record else None,
            }
        },
    )
    async with in_transaction() as connection:
        await (
            AiTask.filter(id=task.id)
            .using_db(connection)
            .update(updated_at=F("updated_at"))
        )
        task = (
            await AiTask.filter(id=task.id)
            .using_db(connection)
            .select_for_update()
            .get()
        )
        event = await AgentOperation.get(id=event.id).using_db(connection)
        if event.state == "completed":
            return
        review_key = task.request_params.get("review_resolution_key", "review:closure")
        review = await AgentOperation.get(task=task, key=review_key).using_db(
            connection
        )
        record = (
            await ModelUsageRecord.get_or_none(id=record.id).using_db(connection)
            if record
            else None
        )
        reasons = []
        if outcome_conflicts(review.result["outcome"], evidence):
            reasons.append("provider_result_contradicts_review")
        billed = (
            quantity(
                (record.usage or {}).get(
                    "image_count" if evidence.kind == "image" else "seconds"
                )
            )
            if record
            else None
        )
        acknowledged = review.result.get("accepted_evidence") or {}
        mismatch = (
            evidence.quantity is not None
            and billed is not None
            and billed != evidence.quantity
        )
        if mismatch and acknowledged.get("quantity") != evidence.quantity:
            reasons.append("reported_usage_differs_from_booked_usage")
        certainty = evidence_certainty(
            task.request_params.get("review_certainty")
            or review.result.get("certainty")
            or {},
            evidence,
            conflict=bool(reasons),
            accounting_pending=mismatch,
        )
        projection = {
            "id": evidence.fingerprint,
            "facts": asdict(evidence),
            "reasons": reasons,
            "usage_record_id": record.id if record else None,
        }
        task.request_params = {
            **task.request_params,
            "review_certainty": certainty,
            "review_evidence": projection,
            "review_conflict": bool(reasons),
        }
        if reasons:
            task.stage = "needs_review"
        await task.save(
            using_db=connection, update_fields=["request_params", "stage", "updated_at"]
        )
        if record:
            record.usage = {
                **record.usage,
                **certainty,
                "reported_usage": asdict(evidence),
                "review_evidence_id": evidence.fingerprint,
            }
            await record.save(using_db=connection, update_fields=["usage"])
        video = await Video.get_or_none(
            id=task.request_params.get("video_id")
        ).using_db(connection)
        if video:
            video.metadata = {
                **(video.metadata or {}),
                **certainty,
                "review_evidence": projection,
            }
            await video.save(
                using_db=connection, update_fields=["metadata", "updated_at"]
            )
        event.result = {
            **event.result,
            "certainty": certainty,
            "reasons": reasons,
            "source_review_key": review_key,
        }
        event.state = "completed"
        await event.save(using_db=connection, update_fields=["result", "state"])


async def retry_review_evidence():
    for event in await AgentOperation.filter(
        key__startswith="review:evidence:", state="pending"
    ).limit(20):
        record = await ModelUsageRecord.get_or_none(
            id=event.result.get("usage_record_id")
        )
        await reconcile_evidence(
            event.task_id, record, MediaEvidence(**event.result["evidence"])
        )
        if (
            event.result["evidence"]["kind"] == "video"
            and await AgentOperation.filter(
                task_id=event.task_id, key="billing:video", state="completed"
            ).exists()
        ):
            task = await AiTask.get(id=event.task_id)
            video = await Video.get_or_none(id=task.request_params.get("video_id"))
            if video:
                video.metadata = {**video.metadata, "billing_pending": False}
                await video.save(update_fields=["metadata", "updated_at"])
