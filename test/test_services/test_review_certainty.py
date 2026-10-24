"""Manual closure preserves separate submission, media and usage knowledge."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.scene import Scene
from models.video import Video
from models.usage_record import ModelUsageRecord
from schemas.ai_task import TaskReviewResolution
from services.creation_agent.review import close_uncertain_task
from services.creation_agent.operation_receipts import execute_step, SubmissionUncertain
from test.test_services.test_skill_workflow import enabled_project


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["not_submitted", "provider_failed", "completed_unrecoverable"]
)
@pytest.mark.parametrize("ledger_before", [False, True])
async def test_manual_review_keeps_video_and_existing_or_delayed_ledger_consistent(
    outcome, ledger_before
):
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    task = await AiTask.create(
        task_type=4,
        status=4,
        stage="needs_review",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=4,
        metadata={
            "agent_run_id": str(task.id),
            "submission_uncertain": True,
            "missing_usage": True,
        },
    )
    task.request_params["video_id"] = video.id
    await task.save()
    await AgentOperation.create(
        task=task, key="media:video", state="uncertain", external=True
    )

    async def create_ledger():
        return await ModelUsageRecord.create(
            novel_id=novel.id,
            task_type=4,
            billing_type="video",
            video_id=video.id,
            cost=Decimal("0"),
            model="unknown",
            status=4,
            usage={"missing_usage": True, "submission_uncertain": True},
        )

    ledger = await create_ledger() if ledger_before else None
    resolution = TaskReviewResolution(
        outcome=outcome,
        note="Provider records were checked by the operator for this submission.",
    )
    await close_uncertain_task(task.id, resolution)
    if ledger is None:
        ledger = await create_ledger()
    # Repeated closure also reconciles a delayed ledger without adding records.
    await close_uncertain_task(task.id, resolution)
    await video.refresh_from_db()
    await ledger.refresh_from_db()
    usage_known = outcome == "not_submitted"
    assert video.metadata["submission_uncertain"] is (not usage_known)
    assert video.metadata["submission_outcome_known"] is True
    assert video.metadata["media_result_recoverable"] is (
        False if outcome == "completed_unrecoverable" else None
    )
    assert video.metadata["usage_known"] is usage_known
    for key in (
        "submission_uncertain",
        "missing_usage",
        "submission_outcome_known",
        "media_result_recoverable",
        "usage_known",
    ):
        assert video.metadata[key] == ledger.usage[key]
    assert ledger.usage["missing_usage"] is (not usage_known)
    assert ledger.cost == Decimal("0")
    assert await ModelUsageRecord.filter(video_id=video.id).count() == 1
    assert await AgentOperation.filter(task=task, key="review:closure").count() == 1
    assert (await AgentOperation.get(task=task, key="media:video")).state == "uncertain"
    # Closing an audit never permits replaying its external operation.
    await AiTask.filter(id=task.id).update(status=2)
    action = AsyncMock()
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, "media:video", action, external=True)
    action.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["not_submitted", "provider_failed", "completed_unrecoverable"]
)
async def test_delayed_image_billing_uses_the_reviewed_certainty(outcome):
    from services.billing.recorder import record_ai_task_usage

    novel, _, _ = await enabled_project()
    task = await AiTask.create(
        task_type=2,
        status=4,
        stage="needs_review",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    resolution = TaskReviewResolution(
        outcome=outcome,
        note="The operator checked provider records after the lost response.",
    )
    task = await close_uncertain_task(task.id, resolution)
    await record_ai_task_usage(task, {})
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    certainty = task.request_params["review_certainty"]
    assert ledger.usage["usage_known"] is (outcome == "not_submitted")
    for key, value in certainty.items():
        assert ledger.usage[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["provider_failed", "completed_unrecoverable"])
async def test_review_retains_explicitly_verified_usage_without_altering_charges(
    outcome,
):
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    task = await AiTask.create(
        task_type=4,
        status=4,
        stage="needs_review",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    video = await Video.create(
        scene=scene, model_type=1, status=4, metadata={"submission_uncertain": True}
    )
    task.request_params["video_id"] = video.id
    await task.save()
    ledger = await ModelUsageRecord.create(
        novel_id=novel.id,
        task_type=4,
        billing_type="video",
        video_id=video.id,
        model="verified",
        cost=Decimal("7.5"),
        status=4,
        usage={
            "seconds": 5,
            "usage_known": True,
            "missing_usage": False,
            "submission_uncertain": False,
        },
    )
    await close_uncertain_task(
        task.id,
        TaskReviewResolution(
            outcome=outcome,
            note="Usage was verified independently of the lost media file.",
        ),
    )
    await video.refresh_from_db()
    await ledger.refresh_from_db()
    assert video.metadata["usage_known"] is True
    assert video.metadata["submission_uncertain"] is False
    assert ledger.usage["usage_known"] is True
    assert ledger.usage["seconds"] == 5
    assert ledger.cost == Decimal("7.5")


@pytest.mark.asyncio
async def test_previous_review_receipt_can_reconcile_legacy_inconsistent_flags():
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    task = await AiTask.create(
        task_type=4,
        status=4,
        stage="review_closed",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    note = "Provider completed the task; file and usage could not be recovered."
    audit = {
        "outcome": "completed_unrecoverable",
        "note": note,
        "user_id": 17,
        "reviewed_at": "2026-10-24T00:00:00+00:00",
        "automatic_retry": False,
    }
    await AgentOperation.create(
        task=task, key="review:closure", state="completed", result=audit
    )
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=4,
        metadata={"submission_uncertain": False, "review_resolution": audit},
    )
    task.request_params["video_id"] = video.id
    await task.save()
    ledger = await ModelUsageRecord.create(
        novel_id=novel.id,
        task_type=4,
        billing_type="video",
        video_id=video.id,
        model="unknown",
        cost=0,
        status=4,
        usage={"missing_usage": True, "submission_uncertain": True},
    )
    await close_uncertain_task(
        task.id, TaskReviewResolution(outcome=audit["outcome"], note=note), user_id=99
    )
    await video.refresh_from_db()
    await ledger.refresh_from_db()
    receipt = await AgentOperation.get(task=task, key="review:closure")
    assert receipt.result["user_id"] == 17
    assert receipt.result["reviewed_at"] == audit["reviewed_at"]
    assert (
        video.metadata["submission_uncertain"]
        == ledger.usage["submission_uncertain"]
        is True
    )
    assert video.metadata["usage_known"] == ledger.usage["usage_known"] is False
    assert await AgentOperation.filter(task=task, key="review:closure").count() == 1


@pytest.mark.asyncio
async def test_review_flag_reconciliation_is_atomic_when_a_ledger_write_fails(
    monkeypatch,
):
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    task = await AiTask.create(
        task_type=4,
        status=4,
        stage="needs_review",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    video = await Video.create(
        scene=scene, model_type=1, status=4, metadata={"submission_uncertain": True}
    )
    task.request_params["video_id"] = video.id
    await task.save()
    await ModelUsageRecord.create(
        novel_id=novel.id,
        task_type=4,
        billing_type="video",
        video_id=video.id,
        model="unknown",
        cost=0,
        status=4,
        usage={"missing_usage": True, "submission_uncertain": True},
    )
    monkeypatch.setattr(
        ModelUsageRecord,
        "save",
        AsyncMock(side_effect=RuntimeError("Ledger unavailable")),
    )
    with pytest.raises(RuntimeError, match="Ledger unavailable"):
        await close_uncertain_task(
            task.id,
            TaskReviewResolution(
                outcome="not_submitted",
                note="Provider confirmed that this submission never arrived.",
            ),
        )
    await task.refresh_from_db()
    await video.refresh_from_db()
    assert task.stage == "needs_review"
    assert "review_certainty" not in task.request_params
    assert video.metadata == {"submission_uncertain": True}
    assert not await AgentOperation.filter(task=task, key="review:closure").exists()


@pytest.mark.asyncio
async def test_closed_review_allows_a_new_explicit_request_without_clearing_usage_uncertainty(
    monkeypatch,
):
    from models.config import AiModelConfig
    from controllers.video import video_controller
    from schemas.video import VideoGenerateRequest

    novel, chapter, _ = await enabled_project()
    model = await AiModelConfig.create(
        name="video",
        model="video",
        task_type=4,
        base_url="https://test.invalid",
        api_key="test",
        is_active=True,
        video_model_type="seedance_2",
        api_protocol="volcengine_ark",
    )
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved", duration=5)
    task = await AiTask.create(
        task_type=4,
        status=4,
        stage="needs_review",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=4,
        metadata={"submission_uncertain": True, "agent_run_id": str(task.id)},
    )
    task.request_params["video_id"] = video.id
    await task.save()
    await close_uncertain_task(
        task.id,
        TaskReviewResolution(
            outcome="completed_unrecoverable",
            note="Provider confirmed completion, but the result is no longer available.",
        ),
    )
    provider = AsyncMock()
    monkeypatch.setattr("controllers.video.get_generator", provider)
    new = await video_controller.generate(
        VideoGenerateRequest(scene_id=scene.id, model_config_id=model.id)
    )
    assert new.id != video.id and new.status == 6
    provider.assert_not_called()
    await video.refresh_from_db()
    assert video.metadata["submission_outcome_known"] is True
    assert video.metadata["submission_uncertain"] is True
    assert video.metadata["usage_known"] is False
