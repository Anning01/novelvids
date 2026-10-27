import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.config import AiModelConfig
from models.creation_agent import AgentSettings
from prompts.skill_pack import SkillSnapshot, snapshot_skills
from services.creation_agent.operation_receipts import execute_step, SubmissionUncertain
from services.creation_agent.skill_execution import prepare_workflow
from utils.enums import TaskStatusEnum


def test_skill_snapshot_is_immutable_and_rejects_unknown_paths():
    raw = snapshot_skills()
    frozen = SkillSnapshot.model_validate(raw)
    assert frozen.read("image")
    with pytest.raises(ValueError):
        frozen.read("../.env")
    raw["contents"]["image"] = "changed"
    assert frozen.read("image") != "changed"
    assert len(frozen.revision) == 64


@pytest.mark.asyncio
async def test_assistant_must_be_enabled_and_support_tool_calls():
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await prepare_workflow({})
    await AgentSettings.create(id=1, configuration={"enabled": True})
    await AiModelConfig.create(
        name="assistant",
        model="test",
        task_type=7,
        api_key="test",
        base_url="https://example.test",
        supports_tool_calls=True,
        is_active=True,
    )
    prepared = await prepare_workflow({})
    assert prepared["skill_snapshot"]["contents"]["base"]
    assert prepared["workflow_version"] == "agent-skills-v1"


@pytest.mark.asyncio
async def test_step_replay_returns_receipt_without_executing_twice():
    task = await AiTask.create(
        task_type=2, request_params={}, status=TaskStatusEnum.running.value
    )
    action = AsyncMock(return_value={"video_id": 42})
    assert await execute_step(task.id, "image", action, external=True) == {
        "video_id": 42
    }
    assert await execute_step(task.id, "image", action, external=True) == {
        "video_id": 42
    }
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_uncertain_external_submit_is_never_automatically_repeated():
    task = await AiTask.create(
        task_type=2, request_params={}, status=TaskStatusEnum.running.value
    )
    action = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        await execute_step(task.id, "image", action, external=True)
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, "image", action, external=True)
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_blocks_next_step():
    task = await AiTask.create(
        task_type=2, request_params={}, status=TaskStatusEnum.cancelled.value
    )
    action = AsyncMock()
    with pytest.raises(ValueError):
        await execute_step(task.id, "image", action)
    action.assert_not_awaited()


@pytest.mark.asyncio
async def test_operation_schema_initializes_safely_twice():
    from tortoise import Tortoise

    task = await AiTask.create(task_type=2, request_params={}, status=2)
    await AgentOperation.create(
        task=task, key="saved", state="completed", result={"saved": True}
    )
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.generate_schemas(safe=True)
    assert (await AgentOperation.get(task=task, key="saved")).result == {"saved": True}


@pytest.mark.asyncio
async def test_parallel_external_submissions_execute_only_once():
    task = await AiTask.create(task_type=2, request_params={}, status=2)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def submit():
        entered.set()
        await release.wait()
        return {"saved": True}

    first = asyncio.create_task(
        execute_step(task.id, "generate", submit, external=True)
    )
    await entered.wait()
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, "generate", submit, external=True)
    release.set()
    assert await first == {"saved": True}


@pytest.mark.asyncio
async def test_failed_atomic_write_rolls_back_data_and_keeps_failure_receipt():
    from models.novel import Novel

    task = await AiTask.create(task_type=3, request_params={}, status=2)

    async def fail():
        await Novel.create(name="must-roll-back")
        raise ValueError("validation failed")

    with pytest.raises(ValueError):
        await execute_step(task.id, "persist", fail, atomic=True)
    assert not await Novel.filter(name="must-roll-back").exists()
    assert (await AgentOperation.get(task=task, key="persist")).state == "failed"


@pytest.mark.asyncio
async def test_recovery_preserves_unknown_submission_without_calling_provider():
    from services.creation_agent.recovery import ProductionRecovery
    from services.creation_agent.skill_execution import WORKFLOW_VERSION

    task = await AiTask.create(
        task_type=2, request_params={"workflow_version": WORKFLOW_VERSION}, status=2
    )
    await AgentOperation.create(
        task=task, key="media:image", state="running", external=True
    )
    await ProductionRecovery().recover()
    await task.refresh_from_db()
    assert task.stage == "needs_review"
    assert task.status == 4


@pytest.mark.asyncio
async def test_new_image_task_preserves_saved_prompt_and_does_not_append_style():
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )
    from utils.prompt_language import skill_workflow
    from models.novel import Novel
    from models.asset import Asset
    from services.reference.handler import AssetReferenceHandler

    novel = await Novel.create(name="Story", style_key="realistic-general")
    asset = await Asset.create(
        novel=novel,
        canonical_name="Alex",
        asset_type=1,
        base_traits="Exact {user} prompt",
    )
    execution = SkillExecution(
        {"prompt_language": "en", "skill_snapshot": snapshot_skills()},
        None,
        AsyncMock(),
    )
    token = current_execution.set(execution)
    mode = skill_workflow.set(True)
    try:
        with patch(
            "services.reference.handler.generate_for_sora_consistency",
            new=AsyncMock(return_value=[]),
        ) as generate:
            with pytest.raises(RuntimeError):
                await AssetReferenceHandler().execute(
                    {
                        "asset_id": asset.id,
                        "base_url": "https://test.example",
                        "api_key": "test",
                        "model": "test",
                    }
                )
        assert generate.call_args.kwargs["style_prompt"] == ""
        assert generate.call_args.args[0]["base_traits"] == "Exact {user} prompt"
    finally:
        current_execution.reset(token)
        skill_workflow.reset(mode)


async def enabled_project():
    from models.novel import Novel
    from models.chapter import Chapter

    await AgentSettings.create(id=1, configuration={"enabled": True})
    assistant = await AiModelConfig.create(
        name="assistant",
        model="test",
        task_type=7,
        api_key="test",
        base_url="https://example.test",
        supports_tool_calls=True,
        is_active=True,
    )
    novel = await Novel.create(name="Story")
    chapter = await Chapter.create(
        novel=novel, number=1, name="Chapter 1", content="Alex waits."
    )
    return novel, chapter, assistant


@pytest.mark.asyncio
async def test_video_submission_returns_reserved_record_and_only_background_calls_provider():
    from models.scene import Scene
    from controllers.video import video_controller
    from schemas.video import VideoGenerateRequest
    from services.ai_task_executor import ai_task_executor
    from uuid import uuid4

    novel, chapter, assistant = await enabled_project()
    config = await AiModelConfig.create(
        name="video",
        model="test",
        task_type=4,
        api_key="test",
        base_url="https://example.test",
        video_model_type="seedance_2",
        api_protocol="volcengine_ark",
        is_active=True,
    )
    scene = await Scene.create(
        chapter=chapter, sequence=1, prompt="Alex waits.", duration=6
    )
    request = VideoGenerateRequest(
        scene_id=scene.id, model_config_id=config.id, request_id=uuid4()
    )
    with patch("controllers.video.get_generator") as factory:
        factory.return_value = AsyncMock(submit=AsyncMock(return_value="provider-task"))
        video = await video_controller.generate(request)
        replay = await video_controller.generate(request)
        assert video.id == replay.id
        assert (await video_controller.query_status(video.id)).status == 6
        factory.assert_not_called()
        task = await AiTask.get(id=video.metadata["agent_run_id"])
        await ai_task_executor.run(task)
        await video.refresh_from_db()
        await task.refresh_from_db()
        assert video.external_task_id == "provider-task"
        assert task.stage == "waiting_media"
        assert task.status == 2
        factory.return_value.submit.assert_awaited_once()
        assert factory.return_value.submit.call_args.kwargs["prompt"] == "Alex waits."


@pytest.mark.asyncio
async def test_new_text_generation_uses_snapshot_agent_and_persists_validated_result():
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from models.asset import Asset

    novel, chapter, assistant = await enabled_project()

    def respond(messages, info):
        assert "任务语言 language=" in info.instructions
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool.name,
                    {
                        "persons": [
                            {
                                "name": "Alex",
                                "label": "人物",
                                "aliases": [],
                                "description": "Detective",
                                "base_traits": "A complete natural visual prompt, without fixed labels.",
                            }
                        ],
                        "scenes": [],
                        "items": [],
                    },
                )
            ]
        )

    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch("services.creation_agent.handler.configured_model", return_value=model):
        task = await chapter_controller.extract(chapter.id)
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert (
        await Asset.get(novel=novel, canonical_name="Alex")
    ).base_traits == "A complete natural visual prompt, without fixed labels."
    assert task.response_data["conversation_id"]


@pytest.mark.asyncio
async def test_storyboard_replacement_keeps_original_until_candidate_saves_atomically():
    from controllers.scene import scene_controller
    from models.scene import Scene
    from services.ai_task_executor import ai_task_executor
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from test.test_services.test_prompt_language import _shot
    from prompts.storyboard import format_storyboard_prompt

    candidate = _shot()
    candidate.actions = ["0s-4s: rain falls."]
    candidate.reference_only_types = ["人物", "场景", "物品"]
    expected_prompt = format_storyboard_prompt(candidate, "en")

    novel, chapter, _ = await enabled_project()
    old = await Scene.create(
        chapter=chapter,
        sequence=1,
        prompt="Existing shot",
        description="Original",
        duration=4,
    )

    def respond(messages, info):
        shot = candidate.model_dump(exclude={"prompt"})
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"shots": [shot]})]
        )

    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch("services.creation_agent.handler.configured_model", return_value=model):
        task = await scene_controller.generate(chapter.id, replace_existing=True)
        assert await Scene.filter(id=old.id).exists()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert not await Scene.filter(id=old.id).exists()
    assert await Scene.with_deleted().filter(id=old.id).exists()
    assert str(old.id) in task.request_params["replaced_scene_snapshots"]
    assert await Scene.filter(chapter=chapter).count() == 1
    assert (await Scene.get(chapter=chapter)).prompt == expected_prompt


@pytest.mark.asyncio
async def test_failed_storyboard_generation_never_removes_existing_shots():
    from controllers.scene import scene_controller
    from models.scene import Scene
    from services.ai_task_executor import ai_task_executor

    novel, chapter, _ = await enabled_project()
    old = await Scene.create(chapter=chapter, sequence=1, prompt="Keep me", duration=4)
    with patch(
        "services.creation_agent.skill_execution.SkillExecution.generate",
        new=AsyncMock(side_effect=ValueError("bad candidate")),
    ):
        task = await scene_controller.generate(chapter.id, replace_existing=True)
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    assert (await Scene.get(id=old.id)).prompt == "Keep me"


@pytest.mark.asyncio
async def test_only_child_model_usage_is_charged_once_on_parent_completion_and_replay():
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from services.billing.recorder import record_ai_task_usage
    from models.usage_record import ModelUsageRecord
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.usage import RequestUsage

    novel, chapter, assistant = await enabled_project()
    assistant.pricing = {
        "type": "text",
        "currency": "CNY",
        "input_price_per_1m": 1,
        "output_price_per_1m": 2,
    }
    await assistant.save()

    def respond(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {"persons": [], "scenes": [], "items": []},
                )
            ],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
        )

    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch("services.creation_agent.handler.configured_model", return_value=model):
        task = await chapter_controller.extract(chapter.id)
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    children = [
        row
        for row in await AiTask.all()
        if row.request_params.get("parent_task_id") == str(task.id)
    ]
    assert len(children) == 1
    await record_ai_task_usage(children[0], result=children[0].response_data)
    await record_ai_task_usage(task, result=task.response_data)
    records = await ModelUsageRecord.filter(novel_id=novel.id)
    assert len(records) == 1
    assert records[0].ai_task_id == children[0].id
    assert records[0].usage["input_tokens"] == 100
    assert records[0].usage["output_tokens"] == 20
    assert "api_key" not in str(task.request_params)
    assert "api_key" not in str(children[0].request_params)


@pytest.mark.asyncio
async def test_cross_project_or_read_only_generation_grant_cannot_submit():
    from schemas.agent_workflow import ProductionIntent
    from schemas.creation_agent import AgentRunRequest
    from services.creation_agent.intent_tools import submit_intent
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )
    from models.novel import Novel
    from models.asset import Asset
    from uuid import uuid4

    novel, chapter, _ = await enabled_project()
    other = await Novel.create(name="Other project")
    asset = await Asset.create(novel=other, canonical_name="Other", asset_type=1)
    intent = ProductionIntent(operation="image", target_id=asset.id, request_id=uuid4())
    request = AgentRunRequest(
        request_id=uuid4(),
        message="生成图片",
        write_scope="project",
        production_intents=[intent],
    )
    execution = SkillExecution({"task_id": str(uuid4())}, None, AsyncMock())
    token = current_execution.set(execution)
    try:
        with pytest.raises(ValueError, match="不属于"):
            await submit_intent(intent, request=request, novel_id=novel.id)
        own = await Asset.create(novel=novel, canonical_name="Own", asset_type=1)
        intent = intent.model_copy(update={"target_id": own.id})
        request = request.model_copy(
            update={"write_scope": "read_only", "production_intents": [intent]}
        )
        with pytest.raises(ValueError, match="只读"):
            await submit_intent(intent, request=request, novel_id=novel.id)
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant_selected", [False, True])
async def test_chat_submission_uses_same_image_admission_and_reuses_receipt(
    variant_selected,
):
    from models.asset import Asset
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )
    from services.creation_agent.intent_tools import submit_intent
    from schemas.creation_agent import AgentRunRequest
    from schemas.agent_workflow import ProductionIntent
    from uuid import uuid4

    novel, chapter, assistant = await enabled_project()
    image_model = await AiModelConfig.create(
        name="image",
        model="image",
        task_type=2,
        api_key="test",
        base_url="https://example.test",
        image_model_type="seedream_5_lite",
        api_protocol="volcengine_ark",
        is_active=True,
    )
    asset = await Asset.create(
        novel=novel,
        canonical_name="Alex",
        asset_type=1,
        base_traits="Saved prompt",
        source_chapters=[1],
    )
    from models.asset_variant import AssetVariant

    variant = (
        await AssetVariant.create(
            asset=asset, name="Coat", base_traits="Variant prompt"
        )
        if variant_selected
        else None
    )
    workflow = await prepare_workflow(
        {"novel_id": novel.id, "chapter_id": chapter.id, "prompt_language": "zh"}
    )
    parent = await AiTask.create(task_type=7, status=2, request_params=workflow)
    execution = SkillExecution(
        {**workflow, "task_id": str(parent.id)}, None, AsyncMock()
    )
    intent = ProductionIntent(
        operation="image",
        target_id=asset.id,
        variant_id=variant.id if variant else None,
        media_model_config_id=image_model.id,
        request_id=uuid4(),
    )
    request = AgentRunRequest(
        request_id=uuid4(),
        message="生成这个角色的图片",
        write_scope="selected",
        targets=[
            {
                "kind": "variant" if variant else "asset",
                "id": variant.id if variant else asset.id,
            }
        ],
        production_intents=[intent],
    )
    token = current_execution.set(execution)
    try:
        first = await submit_intent(intent, request=request, novel_id=novel.id)
        second = await submit_intent(intent, request=request, novel_id=novel.id)
        assert first == second
        child = await AiTask.get(id=first["task_id"])
        assert child.task_type == 2
        assert child.request_params.get("variant_id") == (
            variant.id if variant else None
        )
        assert child.request_params["origin_run_id"] == str(parent.id)
        assert child.request_params["prompt_language"] == "zh"
        assert child.request_params["skill_snapshot"] == workflow["skill_snapshot"]
        assert child.request_params["model_config_id"] == image_model.id
        assert await AiTask.filter(task_type=2).count() == 1
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_image_duplicate_and_cancelled_parent_do_not_create_extra_calls():
    from controllers.asset import asset_controller
    from controllers.ai_task import ai_task_controller
    from models.asset import Asset

    novel, chapter, _ = await enabled_project()
    await AiModelConfig.create(
        name="image",
        model="image",
        task_type=2,
        api_key="test",
        base_url="https://example.test",
        image_model_type="seedream_5_lite",
        api_protocol="volcengine_ark",
        is_active=True,
    )
    asset = await Asset.create(
        novel=novel, canonical_name="Alex", asset_type=1, base_traits="Saved"
    )
    first, second = await asyncio.gather(
        asset_controller.reference(asset.id), asset_controller.reference(asset.id)
    )
    assert first.id == second.id
    parent = await AiTask.create(
        task_type=7, status=2, request_params={"workflow_version": "agent-skills-v1"}
    )
    first.request_params = {**first.request_params, "origin_run_id": str(parent.id)}
    await first.save()
    await ai_task_controller.cancel(parent.id)
    await first.refresh_from_db()
    assert first.status == 5


@pytest.mark.asyncio
async def test_schema_response_hides_snapshots_and_provider_secrets():
    from schemas.ai_task import AiTaskOut

    task = await AiTask.create(
        task_type=2,
        request_params={
            "api_key": "sensitive",
            "base_url": "private",
            "skill_snapshot": {"contents": "private rules"},
            "asset_id": 1,
        },
    )
    output = AiTaskOut.model_validate(task).model_dump()
    assert output["request_params"] == {"asset_id": 1}


@pytest.mark.asyncio
async def test_story_write_receipt_preserves_later_edits_and_no_unrequested_cover():
    from models.novel import Novel
    from services.project_analysis.handler import (
        ProjectAnalysisTaskHandler,
        BookAnalysis,
    )
    from services.creation_agent.skill_execution import current_execution
    from types import SimpleNamespace

    novel, chapter, assistant = await enabled_project()
    await Novel.filter(id=novel.id).update(content="Chapter 1. Alex waits.")
    workflow = await prepare_workflow(
        {"novel_id": novel.id, "prompt_language": "en", "include_cover": False}
    )
    task = await AiTask.create(task_type=5, status=2, request_params=workflow)
    params = {**workflow, "task_id": str(task.id)}
    execution = SimpleNamespace(
        params=params,
        generate=AsyncMock(
            return_value=BookAnalysis(
                book_types=["Drama"], story_outline="An arrival", key_characters=[]
            )
        ),
    )
    token = current_execution.set(execution)
    try:
        with patch(
            "services.project_analysis.handler.generate_images", new_callable=AsyncMock
        ) as generate:
            await ProjectAnalysisTaskHandler().execute(params)
            await Novel.filter(id=novel.id).update(story_outline="User revised outline")
            await ProjectAnalysisTaskHandler().execute(params)
            generate.assert_not_awaited()
        await novel.refresh_from_db()
        assert novel.story_outline == "User revised outline"
        assert (
            await AgentOperation.filter(
                task=task, key="persist:story", state="completed"
            ).count()
            == 1
        )
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_cancelled_queued_video_has_terminal_pollable_record():
    from models.scene import Scene
    from models.video import Video
    from controllers.video import video_controller
    from controllers.ai_task import ai_task_controller

    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    task = await AiTask.create(
        task_type=4,
        status=6,
        request_params={"workflow_version": "agent-skills-v1", "operation": "video"},
    )
    video = await Video.create(
        scene=scene, model_type=1, status=6, metadata={"agent_run_id": str(task.id)}
    )
    task.request_params["video_id"] = video.id
    await task.save()
    await ai_task_controller.cancel(task.id)
    assert (await video_controller.query_status(video.id)).status == 5


@pytest.mark.asyncio
async def test_button_and_worker_share_production_concurrency_limit():
    from services.ai_task_executor import AiTaskExecutor
    from schemas.creation_agent import AgentConfiguration

    executor = AiTaskExecutor()
    entered = asyncio.Event()
    release = asyncio.Event()
    count = 0
    maximum = 0

    async def run(task):
        nonlocal count, maximum
        count += 1
        maximum = max(maximum, count)
        entered.set()
        await release.wait()
        count -= 1

    executor._run_once = run
    tasks = [
        await AiTask.create(
            task_type=2,
            status=1,
            request_params={"workflow_version": "agent-skills-v1"},
        )
        for _ in range(3)
    ]
    with patch(
        "services.creation_agent.sessions.agent_configuration",
        new=AsyncMock(return_value=AgentConfiguration(production_concurrency=1)),
    ):
        pending = [asyncio.create_task(executor.run(task)) for task in tasks]
        await entered.wait()
        await asyncio.sleep(0)
        assert maximum == 1
        release.set()
        await asyncio.gather(*pending)
    assert maximum == 1


def test_voice_protocol_mapping_preserves_names_and_audio_order():
    import json
    from prompts.skill_pack import render_voice_bindings

    payload = json.loads(
        render_voice_bindings(
            [
                {"subjects": ["Alex Chen"], "kind": "character", "index": 1},
                {"subjects": ["Sam Lee"], "kind": "character", "index": 1},
                {"subjects": [], "kind": "narrator", "index": 2},
            ]
        )
    )
    assert [item["reference"] for item in payload["voice_bindings"]] == [
        "[音频1]",
        "[音频1]",
        "[音频2]",
    ]
    assert payload["voice_bindings"][0]["subjects"] == ["Alex Chen"]
    assert render_voice_bindings([]) == ""


@pytest.mark.asyncio
async def test_lost_response_reuses_completed_server_task_and_rejects_changed_payload():
    from uuid import uuid4
    from controllers.chapter import chapter_controller
    from services.creation_agent.submissions import submission
    from fastapi import HTTPException

    novel, chapter, _ = await enabled_project()
    key = str(uuid4())
    token = submission.set({"submission_id": key, "submission_hash": "same-body"})
    try:
        first = await chapter_controller.extract(chapter.id)
        await AiTask.filter(id=first.id).update(status=3)
        second = await chapter_controller.extract(chapter.id)
        assert first.id == second.id
        changed = submission.set(
            {"submission_id": key, "submission_hash": "changed-body"}
        )
        try:
            with pytest.raises(HTTPException) as error:
                await chapter_controller.extract(chapter.id)
            assert error.value.status_code == 409
        finally:
            submission.reset(changed)
        assert await AiTask.filter(task_type=1).count() == 1
    finally:
        submission.reset(token)


@pytest.mark.asyncio
async def test_media_billing_failure_retries_settlement_without_generating_again(
    monkeypatch,
):
    from services.ai_task_executor import ai_task_executor
    from services.billing.recorder import billing_recorder
    from models.usage_record import ModelUsageRecord

    novel, chapter, assistant = await enabled_project()
    task = await AiTask.create(
        task_type=2,
        status=2,
        request_params={
            "workflow_version": "agent-skills-v1",
            "novel_id": novel.id,
            "model_config_id": assistant.id,
        },
    )
    original = billing_recorder.record_image
    monkeypatch.setattr(billing_recorder, "record_image", AsyncMock(return_value=None))
    await ai_task_executor._complete(task, {"images": ["saved.png"], "image_count": 2})
    await task.refresh_from_db()
    assert task.status == 3 and task.stage == "billing_pending"
    monkeypatch.setattr(billing_recorder, "record_image", original)
    await ai_task_executor._complete(task, task.response_data)
    await ai_task_executor._complete(task, task.response_data)
    await task.refresh_from_db()
    assert task.stage == "completed"
    records = await ModelUsageRecord.filter(ai_task_id=task.id)
    assert len(records) == 1
    assert records[0].usage["image_count"] == 2


@pytest.mark.asyncio
async def test_recovery_settles_known_video_without_repeating_provider_submission(
    monkeypatch,
):
    from models.scene import Scene
    from models.video import Video
    from services.creation_agent.recovery import ProductionRecovery
    from services.ai_task_executor import ai_task_executor

    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="Saved")
    video = await Video.create(
        scene=scene,
        model_type=1,
        status=3,
        external_task_id="already-submitted",
        url="/media/ready.mp4",
    )
    task = await AiTask.create(
        task_type=4,
        status=2,
        request_params={
            "workflow_version": "agent-skills-v1",
            "operation": "video",
            "video_id": video.id,
            "novel_id": novel.id,
        },
    )
    run = AsyncMock(
        side_effect=AssertionError("Must not execute the submitted job again")
    )
    monkeypatch.setattr(ai_task_executor, "run", run)
    recovery = ProductionRecovery()
    await recovery.start()
    try:

        async def completed():
            while True:
                await task.refresh_from_db()
                if task.status == 3:
                    return
                await asyncio.sleep(0.01)

        await asyncio.wait_for(completed(), timeout=2)
    finally:
        await recovery.stop()
    run.assert_not_awaited()
    assert task.response_data["url"] == "/media/ready.mp4"


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_quote", [False, True])
async def test_chat_authorization_uses_only_current_input_and_reuses_its_grant(
    valid_quote,
):
    import json
    from uuid import uuid4
    from models.asset import Asset
    from models.creation_agent import AgentMessage
    from services.creation_agent.authorization import resolve_production_intents
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )
    from schemas.creation_agent import AgentRunRequest
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    novel, chapter, _ = await enabled_project()
    novel.custom_style_prompt = "PRIVATE_PROJECT_INSTRUCTION_GENERATE_EVERYTHING"
    await novel.save()
    asset = await Asset.create(
        novel=novel, canonical_name="Alex Chen", asset_type=1, base_traits="Saved"
    )
    workflow = await prepare_workflow({"novel_id": novel.id, "prompt_language": "en"})
    task = await AiTask.create(task_type=7, status=2, request_params=workflow)
    assistant = await conversation_for_task(task)
    message = await AgentMessage.get(task=task, role="user")
    request = AgentRunRequest(
        request_id=uuid4(),
        message="Generate Alex Chen's image",
        write_scope="selected",
        targets=[{"kind": "asset", "id": asset.id}],
    )
    calls = 0

    def respond(messages, info):
        nonlocal calls
        calls += 1
        assert "PRIVATE_PROJECT_INSTRUCTION_GENERATE_EVERYTHING" not in json.dumps(
            messages, default=str
        )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "intents": [
                            {
                                "operation": "image",
                                "target_id": asset.id,
                                "source_quote": request.message
                                if valid_quote
                                else "Invented authorization",
                            }
                        ]
                    },
                )
            ]
        )

    model = FunctionModel(respond)
    model.client = AsyncMock()
    execution = SkillExecution(
        {**workflow, "task_id": str(task.id)}, assistant, AsyncMock()
    )
    token = current_execution.set(execution)
    try:
        with patch(
            "services.creation_agent.handler.configured_model", return_value=model
        ):
            first = await resolve_production_intents(request, novel.id, message)
            second = await resolve_production_intents(request, novel.id, message)
            assert first.production_intents == second.production_intents == []
            assert bool(message.run_input['production_proposals']) is valid_quote
            read_only = request.model_copy(update={"write_scope": "read_only"})
            assert (
                await resolve_production_intents(read_only, novel.id, message)
                == read_only
            )
        assert calls == 1
        assert not await AiTask.filter(task_type=2).exists()
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrent_edit", [False, True])
async def test_missing_image_prompt_is_saved_but_never_overwrites_a_concurrent_user_edit(
    concurrent_edit,
):
    from models.asset import Asset
    from schemas.agent_workflow import CompletePrompt
    from services.creation_agent.media_execution import prepare_image_prompt
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )

    novel, chapter, _ = await enabled_project()
    asset = await Asset.create(novel=novel, canonical_name="Alex", asset_type=1)

    async def generate(*args):
        if concurrent_edit:
            await Asset.filter(id=asset.id).update(base_traits="User prompt")
        return CompletePrompt(prompt="Complete generated prompt")

    execution = SkillExecution({}, None, AsyncMock())
    execution.generate = AsyncMock(side_effect=generate)
    token = current_execution.set(execution)
    try:
        await prepare_image_prompt(asset, None, {})
        await prepare_image_prompt(asset, None, {})
        await asset.refresh_from_db()
        assert asset.base_traits == (
            "User prompt" if concurrent_edit else "Complete generated prompt"
        )
        execution.generate.assert_awaited_once()
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_remake_agent_sends_video_url_and_never_stores_binary_in_audit(
    tmp_path, monkeypatch
):
    import json
    import httpx
    from openai import AsyncOpenAI
    from models.creation_agent import AgentMessage
    from services.creation_agent.production import conversation_for_task
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )
    from services.remake.gateway import RemakeVideoAnalysisGateway

    novel, chapter, _ = await enabled_project()
    model_config = await AiModelConfig.create(
        name="video analysis",
        model="video-analysis",
        task_type=6,
        base_url="https://analysis.invalid/v1",
        api_key="test",
        supports_tool_calls=True,
        is_active=True,
    )
    workflow = await prepare_workflow({"novel_id": novel.id, "prompt_language": "en"})
    task = await AiTask.create(task_type=6, status=2, request_params=workflow)
    assistant = await conversation_for_task(task)
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"video-fixture" * 10000)
    seen = []

    def transport(request):
        payload = json.loads(request.content)
        seen.append(payload)
        content = next(
            message["content"]
            for message in payload["messages"]
            if message["role"] == "user"
        )
        video = next(item for item in content if item["type"] == "video_url")
        assert video["video_url"]["url"].startswith("data:video/mp4;base64,")
        assert video["video_url"]["fps"] == 1.0
        assert "language=en" in str(payload["messages"])
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 1,
                "model": "video-analysis",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "result",
                                    "type": "function",
                                    "function": {
                                        "name": "final_result",
                                        "arguments": json.dumps(
                                            {
                                                "characters": [],
                                                "scenes": [],
                                                "objects": [],
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 20,
                    "total_tokens": 220,
                },
            },
        )

    monkeypatch.setattr(
        "services.creation_agent.handler.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        ),
    )
    execution = SkillExecution(
        {**workflow, "task_id": str(task.id)}, assistant, AsyncMock()
    )
    token = current_execution.set(execution)
    try:
        result = await RemakeVideoAnalysisGateway(
            model_config, client=AsyncMock()
        ).analyze_one(
            index=1,
            path=path,
            prompt="legacy prompt must not be sent",
            schema_name="global_key_assets",
            response_schema={},
            include_segment_metadata=False,
        )
        assert result == {"characters": [], "scenes": [], "objects": []}
        assert len(seen) == 1
        assert "legacy prompt must not be sent" not in str(seen)
        child_message = (
            await AgentMessage.filter(conversation_id=assistant.conversation_id)
            .order_by("-id")
            .first()
        )
        audit = json.dumps(child_message.native_messages)
        assert "sha256=" in audit and "base64" not in audit
        assert len(audit) < 20000
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_receipt_table_bootstrap_without_full_schema_generation():
    from tortoise import Tortoise
    from services.schema_compat import ensure_agent_operation_schema

    connection = Tortoise.get_connection("default")
    assert connection.filename == ":memory:"
    task = await AiTask.create(task_type=2, status=3, request_params={"legacy": True})
    # This fixture's empty, in-memory new table simulates an older installation.
    await connection.execute_script("DROP TABLE agent_operations;")
    await ensure_agent_operation_schema()
    await AgentOperation.create(
        task=task, key="receipt", state="completed", result={"id": 1}
    )
    await ensure_agent_operation_schema()
    assert (await AgentOperation.get(task=task, key="receipt")).result == {"id": 1}
    assert (await AiTask.get(id=task.id)).request_params == {"legacy": True}


@pytest.mark.asyncio
async def test_failed_media_settlement_keeps_submission_uncertainty(monkeypatch):
    from services.ai_task_executor import ai_task_executor
    from services.billing.recorder import billing_recorder
    from models.usage_record import ModelUsageRecord

    novel, _, assistant = await enabled_project()
    task = await AiTask.create(
        task_type=2,
        status=2,
        request_params={
            "workflow_version": "agent-skills-v1",
            "novel_id": novel.id,
            "model_config_id": assistant.id,
        },
    )
    await AgentOperation.create(
        task=task, key="media:image", state="uncertain", external=True
    )
    error = RuntimeError("Saving failed after the response")
    error.image_count = 2
    original = billing_recorder.record_image
    monkeypatch.setattr(billing_recorder, "record_image", AsyncMock(return_value=None))
    await ai_task_executor._fail(task, "Media needs verification", error=error)
    await task.refresh_from_db()
    assert task.status == 4 and task.stage == "needs_review"
    assert task.request_params["billing_pending"]
    monkeypatch.setattr(billing_recorder, "record_image", original)
    await ai_task_executor._complete(task, task.response_data)
    await task.refresh_from_db()
    assert task.status == 4 and task.stage == "needs_review"
    assert not task.request_params.get("billing_pending")
    assert (await ModelUsageRecord.get(ai_task_id=task.id)).usage["image_count"] == 2


@pytest.mark.asyncio
async def test_joining_an_existing_generation_does_not_replace_its_snapshot_or_owner():
    from uuid import uuid4
    from models.asset import Asset
    from controllers.asset import asset_controller
    from schemas.agent_workflow import ProductionIntent
    from schemas.creation_agent import AgentRunRequest
    from services.creation_agent.skill_execution import (
        SkillExecution,
        current_execution,
    )
    from services.creation_agent.intent_tools import submit_intent

    novel, chapter, _ = await enabled_project()
    image_model = await AiModelConfig.create(
        name="image",
        model="image",
        task_type=2,
        base_url="https://test.invalid",
        api_key="test",
        image_model_type="seedream_5_lite",
        api_protocol="volcengine_ark",
        is_active=True,
    )
    asset = await Asset.create(
        novel=novel, canonical_name="Alex", asset_type=1, base_traits="Saved"
    )
    existing = await asset_controller.reference(
        asset.id, media_model_config_id=image_model.id
    )
    original = dict(existing.request_params)
    params = await prepare_workflow({"novel_id": novel.id, "prompt_language": "zh"})
    parent = await AiTask.create(task_type=7, status=2, request_params=params)
    intent = ProductionIntent(
        operation="image",
        target_id=asset.id,
        media_model_config_id=image_model.id,
        request_id=uuid4(),
    )
    request = AgentRunRequest(
        request_id=uuid4(),
        message="Generate image",
        write_scope="project",
        production_intents=[intent],
    )
    execution = SkillExecution({**params, "task_id": str(parent.id)}, None, AsyncMock())
    token = current_execution.set(execution)
    try:
        result = await submit_intent(intent, request=request, novel_id=novel.id)
        assert result["task_id"] == str(existing.id)
        await existing.refresh_from_db()
        assert existing.request_params == original
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_uncertain_cover_keeps_story_result_and_blocks_duplicate_paid_submission(
    monkeypatch,
):
    from controllers.novel import novel_controller
    from models.novel import Novel
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    from services.project_analysis.handler import BookAnalysis
    from schemas.agent_workflow import CompletePrompt
    from fastapi import HTTPException

    novel, chapter, _ = await enabled_project()
    await Novel.filter(id=novel.id).update(content="Alex waits.")
    await AiModelConfig.create(
        name="image",
        model="image",
        task_type=2,
        api_key="test",
        base_url="https://example.test",
        image_model_type="seedream_5_lite",
        api_protocol="volcengine_ark",
        is_active=True,
    )

    async def generate(self, skill, facts, output_type, **kwargs):
        if output_type is BookAnalysis:
            return BookAnalysis(
                book_types=["Drama"],
                story_outline="Preserved outline",
                key_characters=[],
            )
        return CompletePrompt(prompt="Cover")

    monkeypatch.setattr(SkillExecution, "generate", generate)
    submit = AsyncMock(side_effect=TimeoutError("Lost response"))
    monkeypatch.setattr("services.project_analysis.handler.generate_images", submit)
    task = await novel_controller.analyze(novel.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.stage == "needs_review"
    assert task.response_data["story_outline"] == "Preserved outline"
    assert (await Novel.get(id=novel.id)).story_outline == "Preserved outline"
    with pytest.raises(HTTPException):
        await novel_controller.analyze(novel.id)
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_remake_reuses_uploaded_source_and_original_skill_snapshot():
    from uuid import uuid4
    from models.remake_source import RemakeSource
    from services.creation_agent.skill_execution import SkillExecution, current_execution
    from services.creation_agent.intent_tools import submit_intent
    from schemas.agent_workflow import ProductionIntent
    from schemas.creation_agent import AgentRunRequest

    novel, chapter, _ = await enabled_project()
    original = await prepare_workflow({'novel_id': novel.id, 'chapter_id': chapter.id, 'prompt_language': 'en'})
    failed = await AiTask.create(task_type=6, status=4, request_params=original)
    source = await RemakeSource.create(novel=novel, chapter=chapter, episode_number=1, source_kind='upload',
        storage_provider='local', object_key='uploaded.mp4', original_filename='uploaded.mp4',
        size_bytes=10, duration_seconds=4, width=640, height=480, container_format='mp4', checksum='abc',
        media_status='failed', analysis_task=failed)
    parent_params = await prepare_workflow({'novel_id': novel.id, 'chapter_id': chapter.id, 'prompt_language': 'zh'})
    parent = await AiTask.create(task_type=7, status=2, request_params=parent_params)
    execution = SkillExecution({**parent_params, 'task_id': str(parent.id)}, None, AsyncMock())
    intent = ProductionIntent(operation='remake', target_id=source.id, request_id=uuid4())
    request = AgentRunRequest(request_id=uuid4(), message='Retry this episode', chapter_id=chapter.id,
        write_scope='chapter', production_intents=[intent])
    token = current_execution.set(execution)
    try:
        first = await submit_intent(intent, request=request, novel_id=novel.id)
        second = await submit_intent(intent, request=request, novel_id=novel.id)
        assert first == second
        retry = await AiTask.get(id=first['task_id'])
        assert retry.request_params['prompt_language'] == 'en'
        assert retry.request_params['skill_snapshot'] == original['skill_snapshot']
        assert retry.request_params['remake_source_id'] == source.id
        assert retry.request_params['origin_run_id'] == str(parent.id)
        assert await AiTask.filter(task_type=6).count() == 2
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_model_preflight_failure_is_definite_and_preserves_actual_error():
    task = await AiTask.create(task_type=5, status=2, request_params={'workflow_version': 'agent-skills-v1'})
    action = AsyncMock(side_effect=ValueError('上下文超过配置上限'))
    with pytest.raises(ValueError, match='上下文超过配置上限'):
        await execute_step(task.id, 'model:story', action, external=True, external_started=lambda: False)
    assert (await AgentOperation.get(task=task, key='model:story')).state == 'failed'
    from services.ai_task_executor import ai_task_executor
    await ai_task_executor._fail(task, '上下文超过配置上限', record_usage=False)
    await task.refresh_from_db()
    assert task.stage != 'needs_review'
    assert task.error_message == '上下文超过配置上限'


@pytest.mark.asyncio
async def test_started_model_failure_remains_uncertain_and_cannot_replay():
    task = await AiTask.create(task_type=5, status=2)
    action = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        await execute_step(task.id, 'model:story', action, external=True, external_started=lambda: True)
    assert (await AgentOperation.get(task=task, key='model:story')).state == 'uncertain'
    with pytest.raises(SubmissionUncertain):
        await execute_step(task.id, 'model:story', action, external=True, external_started=lambda: False)
    action.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit_cap', [None, 64000])
async def test_large_story_input_uses_model_limit_and_never_marks_local_rejection_uncertain(explicit_cap):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from models.chapter import Chapter
    from models.novel import Novel
    from models.creation_agent import AgentMessage
    from services.ai_task_executor import ai_task_executor
    from controllers.novel import novel_controller

    novel, _, _ = await enabled_project()
    # Many quoted paragraph breaks expand at the JSON boundary, as in the reported 828-chapter book.
    text = '"这是一个完整段落。"\n' * 4000
    novel.content = text * 30
    await novel.save()
    await Chapter.bulk_create([
        Chapter(novel_id=novel.id, number=index, name=f'第{index}章', content=text)
        for index in range(2, 829)
    ])
    settings = await AgentSettings.get(id=1)
    settings.configuration = {'enabled': True, 'request_limit': 9, 'max_context_characters': explicit_cap}
    await settings.save()
    calls = []

    def respond(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            'book_types': ['冒险'], 'story_outline': 'A complete story outline.', 'key_characters': [],
        })])

    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await novel_controller.analyze(novel.id)
        task.request_params['include_cover'] = False
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    receipt = await AgentOperation.get(task=task, key='model:story:BookAnalysis:')
    if explicit_cap is None:
        assert task.status == 3, task.error_message
        assert calls
        assert receipt.state == 'completed'
    else:
        assert task.status == 4
        assert task.stage != 'needs_review'
        assert any(text in task.error_message for text in ('上下文超过配置上限', 'Context exceeds the limit'))
        assert not calls
        assert receipt.state == 'failed'
        child = await AgentMessage.filter(role='assistant').exclude(task_id=task.id).get()
        assert child is not None and not (child.usage or {}).get('calls')


@pytest.mark.asyncio
async def test_cover_failure_preserves_usable_analysis_in_the_latest_analysis_api(client, monkeypatch):
    from controllers.novel import novel_controller
    from models.novel import Novel
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    from services.project_analysis.handler import BookAnalysis
    from schemas.agent_workflow import CompletePrompt

    novel, _, _ = await enabled_project()
    await Novel.filter(id=novel.id).update(content='第一章\nAlex waits.')
    await AiModelConfig.create(name='image',model='image',task_type=2,api_key='test',
        base_url='https://example.test',image_model_type='seedream_5_lite',api_protocol='volcengine_ark',is_active=True)

    async def generate(self, skill, facts, output_type, **kwargs):
        return BookAnalysis(book_types=['冒险'],story_outline='已保存的故事大纲',key_characters=[]) if output_type is BookAnalysis else CompletePrompt(prompt='Cover')
    monkeypatch.setattr(SkillExecution,'generate',generate)
    submit=AsyncMock(side_effect=TimeoutError('Lost image response'))
    monkeypatch.setattr('services.project_analysis.handler.generate_images',submit)
    task=await novel_controller.analyze(novel.id)
    task.request_params['prompt_language']='zh'
    await task.save()
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.stage == 'needs_review'
    assert task.response_data['analysis_completed'] is True
    assert task.response_data['cover_status'] == 'needs_review'
    response=(await client.get(f'/api/novel/{novel.id}/analysis')).json()['data']
    assert response['response_data']['analysis_completed'] is True
    assert response['response_data']['story_outline'] == '已保存的故事大纲'
    assert '封面' in response['response_data']['cover_warning']
    submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_cover_failure_exposes_verified_story_without_changing_external_receipt(client):
    from models.novel import Novel
    novel, _, _=await enabled_project()
    task=await AiTask.create(task_type=5,status=4,stage='needs_review',request_params={'novel_id':novel.id,'workflow_version':'agent-skills-v1','prompt_language':'zh'},response_data={
        'book_types':['冒险'],'story_outline':'历史已保存大纲','key_characters':[],'chapter_count':1,'cover':None,
    })
    await AgentOperation.create(task=task,key='persist:story',state='completed',result={'novel_id':novel.id})
    cover=await AgentOperation.create(task=task,key='media:cover',state='uncertain',external=True)
    response=(await client.get(f'/api/novel/{novel.id}/analysis')).json()['data']
    assert response['response_data']['analysis_completed'] is True
    assert response['response_data']['cover_status'] == 'needs_review'
    await task.refresh_from_db()
    await cover.refresh_from_db()
    assert 'analysis_completed' not in task.response_data
    assert task.status == 4 and task.stage == 'needs_review' and cover.state == 'uncertain'
