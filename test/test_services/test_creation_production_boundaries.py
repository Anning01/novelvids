"""Paid production boundaries under adversarial language, concurrency and failure."""

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from auth.deps import AuthContext
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.agent_submission import AgentSubmission
from models.asset import Asset
from models.creation_agent import AgentMessage
from schemas.agent_workflow import ProductionAuthorization
from schemas.creation_agent import AgentRunRequest
from services.creation_agent.authorization import (
    resolve_production_intents,
    pending_production,
)
from services.creation_agent.production import conversation_for_task
from services.creation_agent.skill_execution import (
    SkillExecution,
    current_execution,
    prepare_workflow,
)
from test.test_services.test_skill_workflow import enabled_project


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "不要生成图片，只修改提示词",
        "如果我说生成图片，你会直接调用模型吗？",
        "他说：“生成图片”。请帮我理解这句话。",
        "只修改提示词，不要生成",
        "以后可能需要生成图片",
        "Do not generate images. Only edit the prompt.",
        "What happens if I say generate image?",
        'The quoted text says "generate images".',
        "Maybe generate an image later.",
        "Generate images? I only want to change the prompt.",
    ],
)
async def test_even_a_misclassifying_model_cannot_authorize_paid_production(text):
    novel, chapter, _ = await enabled_project()
    asset = await Asset.create(
        novel=novel, canonical_name="Alex", asset_type=1, base_traits="Saved"
    )
    workflow = await prepare_workflow({"novel_id": novel.id, "prompt_language": "en"})
    task = await AiTask.create(task_type=7, status=2, request_params=workflow)
    assistant = await conversation_for_task(task)
    user = await AgentMessage.get(task=task, role="user")
    request = AgentRunRequest(
        request_id=uuid4(),
        message=text,
        write_scope="selected",
        targets=[{"kind": "asset", "id": asset.id}],
    )
    user.run_input = request.model_dump(mode="json")
    await user.save()
    execution = SkillExecution(
        {**workflow, "task_id": str(task.id)}, assistant, AsyncMock()
    )
    execution.generate = AsyncMock(
        return_value=ProductionAuthorization.model_validate(
            {
                "intents": [
                    {"operation": "image", "target_id": asset.id, "source_quote": text}
                ]
            }
        )
    )
    token = current_execution.set(execution)
    try:
        with patch(
            "controllers.asset.asset_controller.reference", new_callable=AsyncMock
        ) as submit:
            resolved = await resolve_production_intents(request, novel.id, user)
            assert resolved.production_intents == []
            proposal = await pending_production(task.id)
            assert proposal["labels"][0]["target_label"] == "Alex"
            assert proposal["intents"][0]["target_id"] == asset.id
            submit.assert_not_awaited()
        assert await AiTask.filter(task_type=2).count() == 0
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["生成图片", "Generate image", "generate images!"])
async def test_exact_command_derives_grant_from_selection_without_model_authorization(
    text,
):
    novel, chapter, _ = await enabled_project()
    asset = await Asset.create(
        novel=novel, canonical_name="Alex", asset_type=1, base_traits="Saved"
    )
    workflow = await prepare_workflow({"novel_id": novel.id, "prompt_language": "en"})
    task = await AiTask.create(task_type=7, status=2, request_params=workflow)
    assistant = await conversation_for_task(task)
    user = await AgentMessage.get(task=task, role="user")
    request = AgentRunRequest(
        request_id=uuid4(), message=text, targets=[{"kind": "asset", "id": asset.id}]
    )
    execution = SkillExecution(
        {**workflow, "task_id": str(task.id)}, assistant, AsyncMock()
    )
    execution.generate = AsyncMock(side_effect=AssertionError("No classifier needed"))
    token = current_execution.set(execution)
    try:
        result = await resolve_production_intents(request, novel.id, user)
        assert len(result.production_intents) == 1
        assert result.production_intents[0].target_id == asset.id
        assert result.production_intents[0].operation == "image"
        execution.generate.assert_not_awaited()
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_database_unique_submission_handles_workers_conflicts_and_rolled_back_admission():
    from services.creation_agent.submissions import (
        submit_once,
        previous_submission,
        submission_key,
    )

    novel, _, _ = await enabled_project()
    params = {
        "novel_id": novel.id,
        "submission_id": str(uuid4()),
        "submission_hash": "same",
    }
    calls = 0

    async def create(connection):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return await AiTask.create(
            task_type=2, status=1, request_params=params, using_db=connection
        )

    first, second = await asyncio.gather(
        submit_once(2, params, create), submit_once(2, params, create)
    )
    assert first.id == second.id and calls == 1
    assert (await previous_submission(2, params)).id == first.id
    with pytest.raises(HTTPException) as error:
        await submit_once(2, {**params, "submission_hash": "different"}, create)
    assert error.value.status_code == 409
    with pytest.raises(IntegrityError):
        await AgentSubmission.create(
            key=submission_key(params), task_type=2, request_hash="same", task=first
        )
    broken = {**params, "submission_id": str(uuid4())}

    async def fail(connection):
        await AiTask.create(
            task_type=2, status=1, request_params=broken, using_db=connection
        )
        raise ValueError("Admission failed")

    with pytest.raises(ValueError):
        await submit_once(2, broken, fail)
    assert await previous_submission(2, broken) is None
    assert await AiTask.filter(task_type=2).count() == 1


@pytest.mark.asyncio
async def test_same_key_different_api_payload_conflicts_while_original_is_active(
    client, monkeypatch
):
    monkeypatch.setattr("services.ai_task_executor.ai_task_executor.run", AsyncMock())
    novel, chapter, _ = await enabled_project()
    headers = {"X-Creation-Request-Id": str(uuid4())}
    first = (
        await client.post(f"/api/chapter/extract/{chapter.id}", headers=headers)
    ).json()
    assert first["code"] == 0
    # Same actor and key, different endpoint/body: conflict precedes active reuse.
    conflict = (
        await client.post(
            "/api/scene/generate/", json={"chapter_id": chapter.id}, headers=headers
        )
    ).json()
    assert conflict["code"] == 409
    replay = (
        await client.post(f"/api/chapter/extract/{chapter.id}", headers=headers)
    ).json()
    assert replay["data"]["id"] == first["data"]["id"]


@pytest.mark.asyncio
async def test_candidate_confirmation_is_a_separate_idempotent_user_request():
    from services.creation_agent.sessions import agent_sessions

    novel, _, _ = await enabled_project()
    asset = await Asset.create(
        novel=novel, canonical_name="Alex", asset_type=1, base_traits="Saved"
    )
    conversation = await agent_sessions.create(novel.id, AuthContext())
    request = AgentRunRequest(
        request_id=uuid4(),
        message="Maybe produce a portrait later",
        targets=[{"kind": "asset", "id": asset.id}],
    )
    task = await agent_sessions.submit(conversation, request, AuthContext())
    assistant = await AgentMessage.get(task=task, role="assistant")
    user = await AgentMessage.get(task=task, role="user")
    execution = SkillExecution(
        {**task.request_params, "task_id": str(task.id)}, assistant, AsyncMock()
    )
    execution.generate = AsyncMock(
        return_value=ProductionAuthorization.model_validate(
            {
                "intents": [
                    {
                        "operation": "image",
                        "target_id": asset.id,
                        "source_quote": request.message,
                    }
                ]
            }
        )
    )
    token = current_execution.set(execution)
    try:
        resolved = await resolve_production_intents(request, novel.id, user)
    finally:
        current_execution.reset(token)
    assert resolved.production_intents == []
    await AiTask.filter(id=task.id).update(status=3)
    proposal = await pending_production(task.id)
    confirmation = AgentRunRequest(
        request_id=proposal["confirmation_request_id"],
        message=proposal["message"],
        chapter_id=proposal["chapter_id"],
        write_scope=proposal["write_scope"],
        targets=proposal["targets"],
        production_intents=proposal["intents"],
    )
    confirmed = await agent_sessions.submit(conversation, confirmation, AuthContext())
    assert confirmed.id != task.id
    again = await agent_sessions.submit(conversation, confirmation, AuthContext())
    assert again.id == confirmed.id
    saved = await AgentMessage.get(task=confirmed, role="user")
    assert saved.run_input["production_intents"] == proposal["intents"]
    assert await pending_production(task.id) is None


@pytest.mark.asyncio
async def test_video_settlement_is_unique_across_callers_and_retries_without_querying_provider(
    monkeypatch,
):
    from models.video import Video
    from models.scene import Scene
    from models.config import AiModelConfig
    from models.usage_record import ModelUsageRecord
    from services.creation_agent.video_settlement import (
        settle_video,
        retry_video_settlements,
    )
    from services.billing.recorder import billing_recorder

    novel, chapter, _ = await enabled_project()
    model = await AiModelConfig.create(
        name="video",
        model="v",
        task_type=4,
        base_url="https://test.invalid",
        api_key="test",
        video_model_type="seedance_2",
        is_active=True,
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 46.0}},
    )
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    # Cancellation never suppresses accounting for already accepted media.
    parent = await AiTask.create(
        task_type=4,
        status=5,
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=3,
        external_task_id="accepted-once",
        metadata={
            "agent_run_id": str(parent.id),
            "novel_id": novel.id,
            "model_config_id": model.id,
            "resolution": "720p",
            "provider_accounting": {"seconds": 5, "status": 3},
            "billing_pending": True,
        },
    )
    parent.request_params["video_id"] = video.id
    await parent.save()
    original = billing_recorder.record_video
    monkeypatch.setattr(billing_recorder, "record_video", AsyncMock(return_value=None))
    await settle_video(video)
    assert (
        await AgentOperation.get(task=parent, key="billing:video")
    ).state == "pending"
    assert await ModelUsageRecord.filter(video_id=video.id).count() == 0
    monkeypatch.setattr(billing_recorder, "record_video", original)
    other = await Video.get(id=video.id)
    await asyncio.gather(settle_video(video), settle_video(other))
    await retry_video_settlements()
    assert await ModelUsageRecord.filter(video_id=video.id).count() == 1
    receipt = await AgentOperation.get(task=parent, key="billing:video")
    usage = await ModelUsageRecord.get(video_id=video.id)
    assert receipt.result["usage_record_id"] == usage.id
    assert receipt.result["external_task_id"] == "accepted-once"
    assert usage.cost > 0
    await parent.refresh_from_db()
    assert parent.status == 5


@pytest.mark.asyncio
async def test_uncertain_task_has_audited_terminal_path_without_replaying_external_step(
    client,
):
    from schemas.ai_task import TaskReviewResolution
    from services.creation_agent.review import close_uncertain_task
    from services.creation_agent.operation_receipts import (
        execute_step,
        SubmissionUncertain,
    )

    novel, _, _ = await enabled_project()
    task = await AiTask.create(
        task_type=2,
        status=4,
        stage="needs_review",
        request_params={"novel_id": novel.id, "workflow_version": "agent-skills-v1"},
    )
    await AgentOperation.create(
        task=task, key="media:image", state="uncertain", external=True
    )
    resolution = {
        "outcome": "completed_unrecoverable",
        "note": "Provider support confirmed completion, but no downloadable output remains.",
    }
    response = await client.post(f"/api/task/{task.id}/review", json=resolution)
    assert response.json()["code"] == 0, response.text
    assert response.json()["data"]["stage"] == "review_closed"
    again = await close_uncertain_task(task.id, TaskReviewResolution(**resolution))
    assert again.status == 4
    assert await AgentOperation.filter(task=task, key="review:closure").count() == 1
    from services.billing.recorder import record_ai_task_usage
    from models.usage_record import ModelUsageRecord
    await record_ai_task_usage(again, {})
    ledger = await ModelUsageRecord.get(ai_task_id=task.id)
    assert ledger.usage['missing_usage'] is True
    assert ledger.usage['submission_uncertain'] is True
    # Even a manual requeue cannot claim the uncertain receipt again.
    await AiTask.filter(id=task.id).update(status=2)
    call = AsyncMock()
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, "media:image", call, external=True)
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_language_changes_only_affect_new_tasks_and_survive_recovery(monkeypatch):
    from models.config import GeneralConfig
    from models.chapter import Chapter
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.recovery import ProductionRecovery

    novel, first_chapter, _ = await enabled_project()
    second_chapter = await Chapter.create(
        novel=novel, number=2, name="Second", content="Sam waits."
    )
    config = await GeneralConfig.create(id=1, prompt_language="en")
    old = await chapter_controller.extract(first_chapter.id)
    config.prompt_language = "zh"
    await config.save()
    new = await chapter_controller.extract(second_chapter.id)
    assert old.request_params["prompt_language"] == "en"
    assert new.request_params["prompt_language"] == "zh"
    await ProductionRecovery().recover()
    observed = []

    async def generate(self, skill, facts, output_type, **kwargs):
        observed.append(self.language)
        return output_type.model_validate({"persons": [], "scenes": [], "items": []})

    monkeypatch.setattr(SkillExecution, "generate", generate)
    await ai_task_executor.run(old)
    await ai_task_executor.run(new)
    assert observed == ["en", "zh"]


@pytest.mark.asyncio
async def test_independent_processes_admit_one_request_and_restart_replays_it(tmp_path):
    import json
    import sys
    from pathlib import Path

    script = """
import asyncio, json, sys
from pathlib import Path
from tortoise import Tortoise
from models.ai_task import AiTask
from services.creation_agent.submissions import submit_once
async def main():
    directory, mode = Path(sys.argv[1]), sys.argv[2]
    await Tortoise.init(db_url='sqlite://' + str(directory / 'race.db'), modules={'models': ['models.ai_task', 'models.agent_submission']})
    try:
        if mode == 'bootstrap':
            await Tortoise.generate_schemas(safe=True)
            print('{}')
            return
        if mode != 'replay':
            (directory / ('ready-' + mode)).write_text('ready')
            for attempt in range(500):
                if (directory / 'ready-1').exists() and (directory / 'ready-2').exists():
                    break
                await asyncio.sleep(.01)
            else:
                raise RuntimeError('Barrier timed out')
        params = {'submission_id': 'shared-id', 'submission_hash': 'same-payload'}
        async def create(connection):
            await asyncio.sleep(.1)
            return await AiTask.create(task_type=2, status=1, request_params=params, using_db=connection)
        task = await submit_once(2, params, create)
        print(json.dumps({'id': str(task.id), 'count': await AiTask.all().count()}))
    finally:
        await Tortoise.close_connections()
asyncio.run(main())
"""

    async def run(mode):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            str(tmp_path),
            mode,
            cwd=Path(__file__).resolve().parents[2],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        assert process.returncode == 0, stderr.decode()
        return json.loads(stdout)

    await run("bootstrap")
    first, second = await asyncio.gather(run("1"), run("2"))
    restarted = await run("replay")
    assert first["id"] == second["id"] == restarted["id"]
    assert first["count"] == second["count"] == restarted["count"] == 1


@pytest.mark.asyncio
async def test_parallel_text_settlement_keeps_one_ledger_and_parent_is_display_only():
    from services.billing.recorder import record_ai_task_usage
    from models.usage_record import ModelUsageRecord

    novel, _, model = await enabled_project()
    model.pricing = {
        "type": "text",
        "currency": "CNY",
        "input_price_per_1m": 1,
        "output_price_per_1m": 2,
    }
    await model.save()
    workflow = await prepare_workflow(
        {"novel_id": novel.id, "model_config_id": model.id, "prompt_language": "en"}
    )
    parent = await AiTask.create(task_type=3, status=3, request_params=workflow)
    child = await AiTask.create(
        task_type=7,
        status=3,
        request_params={**workflow, "parent_task_id": str(parent.id)},
    )
    assistant = await conversation_for_task(child)
    assistant.usage = {
        "calls": [{"status": "completed", "usage_reported": True}],
        "requests": 1,
        "input_tokens": 100,
        "output_tokens": 20,
        "missing_usage": False,
    }
    await assistant.save()
    await asyncio.gather(
        record_ai_task_usage(child, {}), record_ai_task_usage(child, {})
    )
    await record_ai_task_usage(
        parent, {"token_usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    )
    records = await ModelUsageRecord.filter(novel_id=novel.id)
    assert len(records) == 1
    assert records[0].ai_task_id == child.id
    await assistant.refresh_from_db()
    assert assistant.billing_record_id == records[0].id
