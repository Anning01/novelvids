"""Settle a known video result through the parent's unique billing receipt."""

import logging
from dataclasses import asdict
from models.agent_operation import AgentOperation
from services.creation_agent.operation_receipts import record_once
from services.creation_agent.review_evidence import video_evidence, reconcile_evidence
from models.usage_record import ModelUsageRecord

logger = logging.getLogger(__name__)
BILLING_KEY = "billing:video"


async def settle_video(video):
    metadata = video.metadata or {}
    parent_id = metadata.get("agent_run_id")
    accounting = metadata.get("provider_accounting")
    if not parent_id or not accounting:
        return
    await AgentOperation.get_or_create(task_id=parent_id, key=BILLING_KEY)

    async def record():
        from services.billing.recorder import billing_recorder
        from controllers.video import video_controller

        usage = (
            await ModelUsageRecord.filter(video_id=video.id, billing_type="video")
            .order_by("id")
            .first()
        )
        if usage is None:
            usage = await billing_recorder.record_video(
                novel_id=metadata["novel_id"],
                model_config_id=metadata["model_config_id"],
                seconds=accounting["seconds"],
                resolution=metadata.get("resolution"),
                input_video_seconds=metadata.get("input_video_seconds", 0),
                has_video_reference=metadata.get("has_video_reference", False),
                input_image_count=metadata.get("input_image_count", 0),
                status=accounting["status"],
                video_id=video.id,
                team_id=metadata.get("team_id"),
                user_id=metadata.get("user_id"),
            )
            if usage is None:
                raise RuntimeError("Video usage record could not be saved")
            proof = video_evidence(video)
            usage.usage = {
                **usage.usage,
                "provider_evidence": asdict(proof),
                "usage_known": proof.quantity is not None,
                "missing_usage": proof.quantity is None,
            }
            await usage.save(update_fields=["usage"])
            await video_controller._consume_balance(
                usage, metadata.get("team_id"), user_id=metadata.get("user_id")
            )
        await AgentOperation.filter(task_id=parent_id, key=BILLING_KEY).update(
            result={
                "video_id": video.id,
                "usage_record_id": usage.id,
                "external_task_id": video.external_task_id,
            }
        )

    try:
        await record_once(parent_id, BILLING_KEY, record)
        receipt = await AgentOperation.get(task_id=parent_id, key=BILLING_KEY)
        usage = await ModelUsageRecord.get_or_none(
            id=receipt.result.get("usage_record_id")
        )
        if usage is None:
            usage = (
                await ModelUsageRecord.filter(video_id=video.id, billing_type="video")
                .order_by("id")
                .first()
            )
        await reconcile_evidence(parent_id, usage, video_evidence(video))
    except Exception as error:
        logger.warning(
            "Video settlement deferred: video_id=%s error_type=%s",
            video.id,
            type(error).__name__,
        )
        pending = True
    else:
        pending = False
    await video.refresh_from_db()
    video.metadata = {**video.metadata, "billing_pending": pending}
    await video.save(update_fields=["metadata", "updated_at"])


async def retry_video_settlements():
    from models.video import Video

    for operation in (
        await AgentOperation.filter(key=BILLING_KEY, state="pending")
        .select_related("task")
        .limit(20)
    ):
        video = await Video.get_or_none(
            id=operation.task.request_params.get("video_id")
        )
        if video:
            await settle_video(video)
