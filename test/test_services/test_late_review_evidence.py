"""New provider evidence never silently inherits a contradictory manual finding."""

from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.config import AiModelConfig
from models.scene import Scene
from models.video import Video
from models.usage_record import ModelUsageRecord
from schemas.ai_task import TaskReviewResolution
from services.ai_task_executor import ai_task_executor
from services.billing.recorder import record_ai_task_usage
from services.creation_agent.review import close_uncertain_task
from services.creation_agent.video_settlement import settle_video
from test.test_services.test_skill_workflow import enabled_project


async def reviewed_image(outcome, *, existing_ledger):
    novel, _, _ = await enabled_project()
    model = await AiModelConfig.create(
        name="image",
        model="image",
        task_type=2,
        base_url="https://test.invalid",
        api_key="test",
        image_model_type="seedream_5_lite",
        api_protocol="volcengine_ark",
        is_active=True,
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 1}},
    )
    task = await AiTask.create(
        task_type=2,
        status=4,
        stage="needs_review",
        request_params={
            "novel_id": novel.id,
            "model_config_id": model.id,
            "clarity": "1K",
            "workflow_version": "agent-skills-v1",
        },
    )
    await AgentOperation.create(
        task=task, key="media:image", state="uncertain", external=True
    )
    if existing_ledger:
        await record_ai_task_usage(task, {})
        await AgentOperation.get_or_create(
            task=task, key="billing:media", defaults={"state": "completed"}
        )
    resolution = TaskReviewResolution(
        outcome=outcome,
        note="The operator checked provider records after the original timeout.",
    )
    await close_uncertain_task(task.id, resolution)
    await task.refresh_from_db()
    return task, resolution


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["not_submitted", "provider_failed"])
async def test_late_images_reopen_review_even_when_billing_was_already_completed(
    outcome, monkeypatch
):
    task, resolution = await reviewed_image(outcome, existing_ledger=True)
    audit = deepcopy((await AgentOperation.get(task=task, key="review:closure")).result)
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    original_cost, original_usage = ledger.cost, ledger.usage["image_count"]
    charge = AsyncMock()
    monkeypatch.setattr("services.billing.recorder._consume_team_balance", charge)
    result = {"image_count": 2, "images": ["/media/one.png", "/media/two.png"]}
    await ai_task_executor._complete(task, result)
    await ai_task_executor._complete(task, result)
    await task.refresh_from_db()
    await ledger.refresh_from_db()
    assert task.stage == "needs_review"
    assert task.request_params["review_conflict"] is True
    assert ledger.usage["review_conflict"] is True
    assert ledger.usage["reported_usage"]["quantity"] == 2
    assert (
        ledger.usage["usage_known"] is True and ledger.usage["missing_usage"] is False
    )
    assert ledger.usage["accounting_needs_review"] is True
    assert (
        ledger.cost == original_cost and ledger.usage["image_count"] == original_usage
    )
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
    assert (await AgentOperation.get(task=task, key="review:closure")).result == audit
    charge.assert_not_awaited()
    # A replay of the old review cannot erase later evidence.
    await close_uncertain_task(task.id, resolution)
    await task.refresh_from_db()
    assert task.stage == "needs_review"
    assert (await AgentOperation.get(task=task, key="media:image")).state == "uncertain"


@pytest.mark.asyncio
async def test_consistent_late_image_usage_fills_certainty_and_is_charged_once(
    monkeypatch,
):
    task, _ = await reviewed_image("completed_unrecoverable", existing_ledger=False)
    audit = deepcopy((await AgentOperation.get(task=task, key="review:closure")).result)
    charge = AsyncMock()
    monkeypatch.setattr("services.billing.recorder._consume_team_balance", charge)
    result = {"image_count": 2}
    await record_ai_task_usage(task, result)
    await record_ai_task_usage(task, result)
    await task.refresh_from_db()
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    assert task.stage == "review_closed"
    assert (
        ledger.usage["usage_known"] is True and ledger.usage["missing_usage"] is False
    )
    assert ledger.usage["review_conflict"] is False
    assert ledger.usage["image_count"] == 2 and ledger.cost > 0
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
    assert (await AgentOperation.get(task=task, key="review:closure")).result == audit
    charge.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["not_submitted", "provider_failed", "completed_unrecoverable"]
)
@pytest.mark.parametrize("evidence_write_fails", [False, True])
async def test_late_video_evidence_is_checked_before_the_completed_billing_receipt(
    outcome, evidence_write_fails, monkeypatch
):
    novel, chapter, model = await enabled_project()
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
            "novel_id": novel.id,
            "model_config_id": model.id,
            "submission_uncertain": True,
        },
    )
    task.request_params["video_id"] = video.id
    await task.save()
    ledger = await ModelUsageRecord.create(
        novel_id=novel.id,
        task_type=4,
        billing_type="video",
        video_id=video.id,
        model="original",
        cost=Decimal("7.5"),
        status=4,
        usage={"seconds": 0, "missing_usage": True},
    )
    await AgentOperation.create(
        task=task,
        key="billing:video",
        state="completed",
        result={"usage_record_id": ledger.id},
    )
    resolution = TaskReviewResolution(
        outcome=outcome,
        note="The operator recorded the original provider finding before a delayed receipt arrived.",
    )
    await close_uncertain_task(task.id, resolution)
    audit = deepcopy((await AgentOperation.get(task=task, key="review:closure")).result)
    await video.refresh_from_db()
    video.external_task_id = "late-provider-job"
    video.url = "/media/recovered.mp4"
    video.metadata = {
        **video.metadata,
        "provider_accounting": {"seconds": 6, "status": 3, "usage_reported": True},
    }
    await video.save()
    charge = AsyncMock()
    monkeypatch.setattr("controllers.video.video_controller._consume_balance", charge)
    if evidence_write_fails:
        save = ModelUsageRecord.save
        calls = 0

        async def fail_once(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Temporary evidence write failure")
            return await save(self, *args, **kwargs)

        monkeypatch.setattr(ModelUsageRecord, "save", fail_once)
    await settle_video(video)
    if evidence_write_fails:
        from services.creation_agent.review_evidence import retry_review_evidence

        assert video.metadata["billing_pending"] is True
        await retry_review_evidence()
        await video.refresh_from_db()
        assert video.metadata["billing_pending"] is False
    await settle_video(video)
    await task.refresh_from_db()
    await video.refresh_from_db()
    await ledger.refresh_from_db()
    assert task.stage == "needs_review"
    assert ledger.usage["reported_usage"]["quantity"] == 6
    assert ledger.usage["review_conflict"] is True
    for key in (
        "usage_known",
        "missing_usage",
        "submission_uncertain",
        "review_conflict",
        "accounting_needs_review",
    ):
        assert video.metadata[key] == ledger.usage[key]
    assert ledger.cost == Decimal("7.5") and ledger.usage["seconds"] == 0
    assert await ModelUsageRecord.filter(video_id=video.id).count() == 1
    assert (await AgentOperation.get(task=task, key="review:closure")).result == audit
    charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_evidence_recheck_appends_audit_and_never_erases_original_or_recharges(
    monkeypatch,
):
    task, original_resolution = await reviewed_image(
        "not_submitted", existing_ledger=True
    )
    original = deepcopy(
        (await AgentOperation.get(task=task, key="review:closure")).result
    )
    charge = AsyncMock()
    monkeypatch.setattr("services.billing.recorder._consume_team_balance", charge)
    await record_ai_task_usage(
        task, {"image_count": 2, "images": ["/media/recovered.png"]}
    )
    await task.refresh_from_db()
    evidence_id = task.request_params["review_evidence"]["id"]
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    cost = ledger.cost
    with pytest.raises(HTTPException) as denied:
        await close_uncertain_task(
            task.id,
            TaskReviewResolution(
                outcome="not_submitted",
                evidence_id=evidence_id,
                note="Trying to preserve the old no-submission finding against provider evidence.",
            ),
        )
    assert denied.value.status_code == 409
    resolution = TaskReviewResolution(
        outcome="completed",
        evidence_id=evidence_id,
        note="The provider receipt and recovered file confirm completion. The booked amount stays unchanged for separate reconciliation.",
    )
    await close_uncertain_task(task.id, resolution, user_id=19)
    await close_uncertain_task(task.id, resolution, user_id=20)
    await close_uncertain_task(task.id, original_resolution)
    await record_ai_task_usage(
        task, {"image_count": 2, "images": ["/media/recovered.png"]}
    )
    await task.refresh_from_db()
    await ledger.refresh_from_db()
    assert task.stage == "review_closed"
    assert task.request_params["review_conflict"] is False
    assert ledger.usage["usage_known"] is True
    assert ledger.usage["accounting_needs_review"] is True
    assert ledger.cost == cost
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
    assert (
        await AgentOperation.get(task=task, key="review:closure")
    ).result == original
    recheck = await AgentOperation.get(task=task, key="review:recheck:" + evidence_id)
    assert recheck.result["user_id"] == 19
    assert recheck.result["accepted_evidence"]["quantity"] == 2
    assert (
        await AgentOperation.filter(
            task=task, key__startswith="review:recheck:"
        ).count()
        == 1
    )
    charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_evidence_write_retry_cannot_drop_conflict_or_repeat_billing(monkeypatch):
    from services.creation_agent.review_evidence import retry_review_evidence

    task, _ = await reviewed_image("not_submitted", existing_ledger=True)
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    old_save = ModelUsageRecord.save
    attempts = 0

    async def fail_once(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Evidence storage temporarily unavailable")
        return await old_save(self, *args, **kwargs)

    monkeypatch.setattr(ModelUsageRecord, "save", fail_once)
    charge = AsyncMock()
    monkeypatch.setattr("services.billing.recorder._consume_team_balance", charge)
    await ai_task_executor._complete(task, {"image_count": 2})
    await task.refresh_from_db()
    assert task.request_params["billing_pending"] is True
    assert (
        await AgentOperation.filter(
            task=task, key__startswith="review:evidence:", state="pending"
        ).count()
        == 1
    )
    await retry_review_evidence()
    await ai_task_executor._complete(task, {"image_count": 2})
    await task.refresh_from_db()
    await ledger.refresh_from_db()
    assert task.stage == "needs_review"
    assert task.request_params["review_conflict"] is True
    assert not task.request_params.get("billing_pending")
    assert ledger.usage["reported_usage"]["quantity"] == 2
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
    assert (
        await AgentOperation.filter(
            task=task, key__startswith="review:evidence:", state="completed"
        ).count()
        == 1
    )
    charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_configured_video_duration_does_not_verify_missing_supplier_usage(
    monkeypatch,
):
    from services.creation_agent.review_evidence import video_evidence

    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=3,
        metadata={
            "provider_accounting": {"seconds": 6, "status": 3, "usage_reported": False}
        },
    )
    proof = video_evidence(video)
    assert proof.quantity is None
    assert proof.completed is True


@pytest.mark.asyncio
async def test_explicit_zero_supplier_usage_is_not_replaced_by_configured_duration():
    from services.creation_agent.review_evidence import video_evidence

    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=3,
        metadata={
            "provider_accounting": {
                "seconds": 6,
                "reported_seconds": 0,
                "status": 3,
                "usage_reported": True,
            }
        },
    )
    assert video_evidence(video).quantity == 0


@pytest.mark.asyncio
async def test_stale_evidence_cannot_close_a_newer_conflict():
    task, _ = await reviewed_image("not_submitted", existing_ledger=True)
    await record_ai_task_usage(task, {"image_count": 2, "images": ["/media/first.png"]})
    await task.refresh_from_db()
    previous = task.request_params["review_evidence"]["id"]
    await record_ai_task_usage(
        task, {"image_count": 3, "images": ["/media/second.png"]}
    )
    await task.refresh_from_db()
    current = task.request_params["review_evidence"]["id"]
    assert previous != current
    with pytest.raises(HTTPException) as error:
        await close_uncertain_task(
            task.id,
            TaskReviewResolution(
                outcome="completed",
                evidence_id=previous,
                note="This finding was prepared for the previous receipt and must not erase newer facts.",
            ),
        )
    assert error.value.status_code == 409
    await task.refresh_from_db()
    assert task.stage == "needs_review"
    assert task.request_params["review_evidence"]["id"] == current


@pytest.mark.asyncio
async def test_recorded_provider_output_also_blocks_a_later_incompatible_manual_finding():
    task, _ = await reviewed_image("completed_unrecoverable", existing_ledger=False)
    # A fresh independent task that has not been manually reviewed yet.
    params = {
        key: value
        for key, value in task.request_params.items()
        if key not in {"review_certainty", "review_resolution_key", "review_conflict"}
    }
    other = await AiTask.create(
        task_type=2, status=4, stage="needs_review", request_params=params
    )
    await record_ai_task_usage(other, {"image_count": 2})
    with pytest.raises(HTTPException) as denied:
        await close_uncertain_task(
            other.id,
            TaskReviewResolution(
                outcome="not_submitted",
                note="The manual no-submission claim contradicts output already reported by the provider.",
            ),
        )
    assert denied.value.status_code == 409
    assert not await AgentOperation.filter(task=other, key="review:closure").exists()


@pytest.mark.asyncio
async def test_cover_accounting_uses_the_same_evidence_policy_and_existing_ledger():
    task, _ = await reviewed_image("not_submitted", existing_ledger=True)
    task.task_type = 5
    await task.save(update_fields=["task_type"])
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    cost = ledger.cost
    result = {
        "image_usage": {"image_count": 2, "clarity": "1K"},
        "image_config_id": task.request_params["model_config_id"],
        "cover": "/media/recovered-cover.png",
    }
    await record_ai_task_usage(task, result)
    await record_ai_task_usage(task, result)
    await task.refresh_from_db()
    await ledger.refresh_from_db()
    assert task.stage == "needs_review"
    assert ledger.usage["reported_usage"]["quantity"] == 2
    assert ledger.cost == cost
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
