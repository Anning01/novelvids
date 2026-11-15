from test.agent_stream_fixtures import completion_stream_response, streaming_model
from unittest.mock import AsyncMock

import pytest

from models.asset import Asset
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.changes import CreationChanges
from test.test_services.test_creation_agent_crud import crud


def test_preflight_facts_are_sent_as_user_data_without_changing_the_system_prefix():
    import json
    from prompts.creation_agent import render_creation_request
    facts = {'creation_contexts': [{'chapter_id': 1, 'constraints_for_new_objects': [{'content': '只用蓝色'}]}]}
    payload = json.loads(render_creation_request('新增雨衣', {'write_scope': 'chapter'}, facts))
    assert payload['preflight_context'] == facts
    assert payload['user_request'] == '新增雨衣'
    assert 'preflight_context' not in json.loads(render_creation_request('旧客户端请求'))


@pytest.mark.asyncio
async def test_new_run_with_no_creation_constraints_does_not_need_a_paid_read_round():
    previous, scene, _, _, task = await crud()
    changes = CreationChanges(novel_id=previous.novel_id, task_id=task.id,
        request=previous.request, max_batch_size=8)
    result = await changes.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'create_setting', 'client_ref': 'coat', 'name': '蓝色雨衣', 'asset_type': 3,
        'description': '蓝色长款雨衣', 'prompt': '蓝色长款雨衣，完整展示材质与轮廓',
    }]}), tool_call_id='create-without-empty-read')
    assert result.changes[0]['target_label'] == '蓝色雨衣'
    assert await Asset.filter(novel_id=previous.novel_id, canonical_name='蓝色雨衣').count() == 1


@pytest.mark.asyncio
async def test_preflight_exposes_constraints_and_still_rejects_changes_after_read(monkeypatch):
    previous, scene, _, _, task = await crud()
    changes = CreationChanges(novel_id=previous.novel_id, task_id=task.id,
        request=previous.request, max_batch_size=8)
    rules = AsyncMock(return_value=[{'content': '雨衣必须是蓝色', 'scope': {'chapter_id': scene.chapter_id}}])
    monkeypatch.setattr('services.creation_agent.changes.creation_memory.for_generation', rules)
    context = await changes.prepare_context()
    assert context['creation_contexts'][0]['constraints_for_new_objects'][0]['content'] == '雨衣必须是蓝色'
    rules.return_value = [{'content': '雨衣必须是黄色', 'scope': {'chapter_id': scene.chapter_id}}]
    with pytest.raises(ValueError, match='上下文|约束'):
        await changes._check_creation_context(scene.chapter_id)


@pytest.mark.asyncio
async def test_unread_nonempty_constraints_are_never_marked_as_read(monkeypatch):
    previous, scene, _, _, task = await crud()
    changes = CreationChanges(novel_id=previous.novel_id, task_id=task.id,
        request=previous.request, max_batch_size=8)
    monkeypatch.setattr('services.creation_agent.changes.creation_memory.for_generation', AsyncMock(return_value=[{'content': '不可戴帽子'}]))
    with pytest.raises(ValueError, match='上下文|约束'):
        await changes._check_creation_context(scene.chapter_id)
    assert scene.chapter_id not in changes.creation_rules


@pytest.mark.asyncio
async def test_child_phases_share_one_durable_repair_allowance():
    from services.creation_agent.reliability import recovery_root, claim_repair, RepairExhausted
    _, _, _, _, task = await crud()
    child = await AiTask.create(task_type=7, status=2, request_params={'parent_task_id': str(task.id)})
    root = await recovery_root({'task_id': str(child.id)})
    assert root == str(task.id)
    await claim_repair(root, [{'tool': 'assets', 'code': 'json_invalid'}])
    # A new wrapper/worker cannot reset the allowance, including a different error.
    with pytest.raises(RepairExhausted):
        await claim_repair(await recovery_root({'task_id': str(child.id)}), [{'tool': 'storyboard', 'code': 'missing'}])


@pytest.mark.asyncio
async def test_invalid_json_keeps_original_response_and_stops_before_third_paid_request():
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from schemas.agent_workflow import CompletePrompt
    from services.creation_agent.model_boundary import RecordedAgentModel
    from services.creation_agent.reliability import RepairExhausted
    from models.creation_agent import AgentConversation
    changes, _, _, _, task = await crud()
    conversation = await AgentConversation.create(novel_id=changes.novel_id)
    message = await AgentMessage.create(conversation=conversation, task=task, request_id=task.id,
        request_hash='test', role='assistant')
    calls = []

    def respond(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, '{"prompt": "unclosed')])

    model = RecordedAgentModel(streaming_model(respond), message=message, before_request=AsyncMock(),
        max_characters=None, repair_root=str(task.id), stage='assets')
    with pytest.raises(RepairExhausted):
        await Agent(output_type=CompletePrompt, retries=3).run('生成', model=model)
    assert len(calls) == 2
    saved = await AgentOperation.filter(task=task, key__startswith='model-response:').order_by('id')
    assert len(saved) == 2
    assert saved[0].result['messages'][0]['parts'][0]['args'] == '{"prompt": "unclosed'
    failure = await AgentOperation.get(task=task, key='recovery:failure')
    assert failure.result['issues'][0]['code'] == 'json_invalid'
    assert 'input' not in failure.result['issues'][0]
    await message.refresh_from_db()
    assert message.usage['requests'] == 2
    await AiTask.filter(id=task.id).update(status=4)
    await task.refresh_from_db()
    from services.creation_agent.reliability import recovery_summary
    summary = await recovery_summary(task)
    assert summary['error_code'] == 'CREATION_JSON_INVALID' and summary['responses_saved'] == 1
    assert summary['can_resume'] is False and 'unclosed' not in str(summary)


@pytest.mark.asyncio
async def test_asset_extraction_source_does_not_authorize_storyboard_or_prose():
    from unittest.mock import patch
    from schemas.creation_plan import CreationPlan, CreationBrief, CreativeRequirement
    from services.creation_agent.plans import CreationPlanner
    from test.test_services.test_creation_plans import plan_fixture
    _, request, chapters, _, source, execution = await plan_fixture()
    chapter = chapters[0]
    request = request.model_copy(update={'message': '从本章提取方天画戟，保留正文不变', 'write_scope': 'chapter'})
    brief = CreationBrief(operations=['assets'], read_chapter_ids=[chapter.id], asset_chapter_ids=[chapter.id],
        requirements=[CreativeRequirement(id='prop', instruction='提取道具', source_quote='提取方天画戟', acceptance='保留正文')])
    plan = CreationPlan(novel_id=chapter.novel_id, source_message_id=source.id,
        original_request=request.model_dump(mode='json'), brief=brief, summary='只提取道具',
        steps=[{'id': 'prop', 'operation': 'assets', 'target_id': chapter.id,
                'requirement_ids': ['prop'], 'instructions': '只提取方天画戟', 'label': '提取道具'}])
    planner = CreationPlanner(execution, source)
    with patch('services.creation_agent.intent_tools.validate_intent_scope', AsyncMock()) as validate:
        await planner.validate_steps(plan, request)
        assert validate.call_args.kwargs['request'].write_scope == 'chapter'
        plan.steps[0].operation = 'storyboard'
        plan.brief.operations = ['storyboard']
        with pytest.raises(ValueError, match='参考章节'):
            await planner.validate_steps(plan, request)
    await chapter.refresh_from_db()
    assert chapter.content == chapters[0].content


def test_asset_checkpoint_keeps_nine_valid_designs_and_repairs_only_failed_one():
    from services.extraction.validation import AssetCandidateValidator
    from services.extraction.extractor import AssetExtractionResult
    from test.test_services.test_asset_design_instructions import fixed_asset_prompt
    valid = fixed_asset_prompt(kind='item')
    first = AssetExtractionResult(persons=[], scenes=[], items=[{'name': str(i), 'description': '道具',
        'base_traits': valid if i < 9 else ''} for i in range(10)])
    validator = AssetCandidateValidator()
    accepted = validator.merge(first)
    assert len(accepted.items) == 9 and len(validator.issues) == 1
    restored = AssetCandidateValidator()
    restored.restore({'accepted': accepted.model_dump(mode='json'), 'issues': validator.issues,
        'pending': [[list(key), issue] for key, issue in validator.pending.items()]}, AssetExtractionResult)
    repaired = restored.merge(AssetExtractionResult(persons=[], scenes=[], items=[
        {'name': '0', 'description': '不可覆盖', 'base_traits': 'invalid'},
        {'name': '9', 'description': '道具', 'base_traits': valid}]))
    assert len(repaired.items) == 10 and not restored.issues
    assert repaired.items[0].description == '道具'


def test_missing_field_in_one_asset_does_not_discard_nine_valid_assets():
    from services.extraction.validation import AssetCandidateValidator
    from services.extraction.extractor import AssetExtractionResult
    from test.test_services.test_asset_design_instructions import fixed_asset_prompt
    validator = AssetCandidateValidator(AssetExtractionResult)
    valid = fixed_asset_prompt(kind='item')
    draft = validator.draft_type.model_validate({'persons': [], 'scenes': [], 'items': [
        *[{'name': str(index), 'base_traits': valid} for index in range(9)], {'name': '9'}]})
    accepted = validator.merge(draft)
    assert len(accepted.items) == 9 and len(validator.issues) == 1
    assert 'base_traits' in validator.issues[0]
    repaired = validator.merge(validator.draft_type.model_validate({'persons': [], 'scenes': [], 'items': [
        {'name': '9', 'base_traits': valid}, {'name': '0', 'base_traits': '不得覆盖'}]}))
    assert len(repaired.items) == 10 and not validator.issues
    assert repaired.items[0].base_traits == valid


@pytest.mark.asyncio
async def test_resume_freezes_scope_reuses_receipts_and_is_idempotent():
    from uuid import uuid4
    from auth.deps import AuthContext
    from schemas.creation_agent import AgentRunRequest
    from services.creation_agent.sessions import agent_sessions
    from services.creation_agent.run_recovery import checkpoint_inputs
    from test.test_services.test_creation_agent_sessions import session_fixture
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'targets': [], 'write_scope': 'chapter', 'message': '提取本章资产，保留原文'})
    task = await agent_sessions.submit(conversation, request, AuthContext())
    await checkpoint_inputs(task.request_params)
    await AgentOperation.create(task=task, key='model:source_reading:SourceReading:page1', state='completed',
        result={'summary': '已读原文', 'candidates': []})
    await AgentOperation.create(task=task, key='model:creation_planning:CreationPlanDraft:', state='failed', external=True)
    await AiTask.filter(id=task.id).update(status=4)
    forged = AgentRunRequest(request_id=uuid4(), message='篡改为全书视频', write_scope='project', resume_from_task_id=task.id)
    resumed = await agent_sessions.submit(conversation, forged, AuthContext())
    assert resumed.id != task.id
    user = await AgentMessage.get(task=resumed, role='user')
    assert user.run_input['message'] == request.message
    assert user.run_input['write_scope'] == 'chapter' and user.run_input['chapter_id'] == request.chapter_id
    assert resumed.request_params['skill_snapshot'] == task.request_params['skill_snapshot']
    assert resumed.request_params['recovery_root_task_id'] == str(task.id)
    assert (await AgentOperation.get(task=resumed, key='model:source_reading:SourceReading:page1')).result['summary'] == '已读原文'
    assert (await AgentOperation.get(task=resumed, key='model:creation_planning:CreationPlanDraft:')).state == 'pending'
    assert (await agent_sessions.submit(conversation, forged.model_copy(update={'request_id': uuid4()}), AuthContext())).id == resumed.id


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked_by', ['changed_source', 'foreign_conversation', 'cancelled', 'uncertain', 'repair_exhausted', 'changed_model'])
async def test_resume_never_replays_changed_cancelled_or_uncertain_work(blocked_by):
    from uuid import uuid4
    from fastapi import HTTPException
    from auth.deps import AuthContext
    from models.chapter import Chapter
    from schemas.creation_agent import AgentRunRequest
    from services.creation_agent.sessions import agent_sessions
    from services.creation_agent.run_recovery import checkpoint_inputs
    from test.test_services.test_creation_agent_sessions import session_fixture
    conversation, request, config = await session_fixture()
    request = request.model_copy(update={'targets': [], 'write_scope': 'chapter'})
    task = await agent_sessions.submit(conversation, request, AuthContext())
    await checkpoint_inputs(task.request_params)
    await AiTask.filter(id=task.id).update(status=5 if blocked_by == 'cancelled' else 4)
    if blocked_by == 'changed_source':
        chapter = await Chapter.get(id=request.chapter_id)
        chapter.content += '用户改动'
        await chapter.save()
    elif blocked_by == 'changed_model':
        config.model = 'new-model'
        await config.save()
    elif blocked_by == 'foreign_conversation':
        conversation = await agent_sessions.create(conversation.novel_id, AuthContext())
    elif blocked_by == 'uncertain':
        await AgentOperation.create(task=task, key='model:unknown', state='uncertain', external=True)
    elif blocked_by == 'repair_exhausted':
        await AgentOperation.create(task=task, key='recovery:repair', state='completed')
    if blocked_by == 'uncertain':
        resumed = await agent_sessions.submit(conversation, AgentRunRequest(request_id=uuid4(), message='继续', resume_from_task_id=task.id), AuthContext())
        assert resumed.id != task.id
        assert await AgentOperation.filter(task=resumed, key='model:unknown', state='pending').exists()
    else:
        with pytest.raises(HTTPException):
            await agent_sessions.submit(conversation, AgentRunRequest(request_id=uuid4(), message='继续', resume_from_task_id=task.id), AuthContext())
        assert await AiTask.filter(task_type=7).count() == 1


@pytest.mark.asyncio
async def test_structured_json_generation_sends_configured_response_format_without_output_tool(monkeypatch):
    import json
    import httpx
    from openai import AsyncOpenAI
    from schemas.agent_workflow import CompletePrompt
    from services.creation_agent.skill_execution import SkillExecution, prepare_workflow
    from services.creation_agent.production import conversation_for_task
    from test.test_services.test_skill_workflow import enabled_project
    novel, _, config = await enabled_project()
    config.supports_json_output = True
    await config.save()
    workflow = await prepare_workflow({'novel_id': novel.id, 'prompt_language': 'zh'})
    task = await AiTask.create(task_type=7, status=2, request_params=workflow)
    message = await conversation_for_task(task)
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return completion_stream_response({'id': 'local', 'created': 1, 'model': 'test', 'object': 'chat.completion',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '{"prompt":"完整设计"}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10, 'total_tokens': 110}})

    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    output = await SkillExecution({**workflow, 'task_id': str(task.id)}, message, AsyncMock()).generate('structured', {}, CompletePrompt)
    assert output.prompt == '完整设计' and len(seen) == 1
    assert seen[0]['response_format'] == {'type': 'json_object'}
    assert not seen[0].get('tools')


@pytest.mark.asyncio
async def test_full_object_rewrite_renders_contract_and_replay_does_not_regenerate(monkeypatch):
    from schemas.creation_agent import AgentTarget
    from services.creation_agent.object_drafts import revise_object, AssetDesignDraft
    from services.creation_agent.skill_execution import SkillExecution, current_execution
    from test.test_services.test_asset_design_instructions import synthetic_snapshot
    service, _, asset, _, task = await crud()
    asset.asset_type = 3
    await asset.save()
    execution = SkillExecution({'task_id': str(task.id), 'prompt_language': 'zh',
        'skill_snapshot': synthetic_snapshot().model_dump()}, None, AsyncMock())

    async def generate(skill, facts, output_type, **options):
        assert skill == 'structured'
        draft = AssetDesignDraft(description='钢制道具', design='A concrete steel prop with clear structural relationships.')
        await options['output_validator'](draft)
        return draft

    model = AsyncMock(side_effect=generate)
    monkeypatch.setattr(execution, 'generate', model)
    token = current_execution.set(execution)
    target = AgentTarget(kind='asset', id=asset.id)
    try:
        first = await revise_object(service, execution, target, '改为钢制', 'rewrite-once')
        replay = await revise_object(service, execution, target, '改为钢制', 'rewrite-once')
        with pytest.raises(ValueError, match='不同的修改要求'):
            await revise_object(service, execution, target, '改为木制', 'rewrite-once')
    finally:
        current_execution.reset(token)
    assert first.id == replay.id and model.await_count == 1
    await asset.refresh_from_db()
    assert asset.base_traits.startswith('Description:item:') and asset.base_traits.endswith('END-GUARD')


@pytest.mark.asyncio
async def test_draft_conflict_retains_candidate_without_overwriting_user_edit(monkeypatch):
    from schemas.creation_agent import AgentTarget
    from services.creation_agent.object_drafts import revise_object, AssetDesignDraft
    from services.creation_agent.skill_execution import SkillExecution, current_execution
    from test.test_services.test_asset_design_instructions import synthetic_snapshot
    service, _, asset, _, task = await crud()
    asset.asset_type = 3
    await asset.save()
    execution = SkillExecution({'task_id': str(task.id), 'prompt_language': 'zh',
        'skill_snapshot': synthetic_snapshot().model_dump()}, None, AsyncMock())

    async def generate(*args, **kwargs):
        asset.base_traits = '用户刚刚修改的设计'
        await asset.save()
        return AssetDesignDraft(description='道具', design='Concrete metal design')

    monkeypatch.setattr(execution, 'generate', AsyncMock(side_effect=generate))
    token = current_execution.set(execution)
    try:
        with pytest.raises(ValueError):
            await revise_object(service, execution, AgentTarget(kind='asset', id=asset.id), '重写', 'conflict')
    finally:
        current_execution.reset(token)
    await asset.refresh_from_db()
    assert asset.base_traits == '用户刚刚修改的设计'
    assert await AgentOperation.filter(task=task, key__startswith='draft:', state='completed').count() == 1


@pytest.mark.asyncio
async def test_initial_model_request_contains_observed_targets_and_rules_before_writing(monkeypatch):
    import json
    from auth.deps import AuthContext
    from models.creation_agent import CreationConstraint, PromptChange
    from pydantic_ai.models.function import FunctionModel, DeltaToolCall
    from pydantic_ai.messages import UserPromptPart
    from services.creation_agent.handler import CreationAgentTaskHandler
    from services.creation_agent.sessions import agent_sessions
    from services.ai_task_executor import AiTaskExecutor
    from utils.enums import AiTaskTypeEnum
    from test.test_services.test_creation_agent_sessions import session_fixture
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'write_scope': 'selected'})
    task = await agent_sessions.submit(conversation, request, AuthContext())
    source = await AgentMessage.get(task=task, role='user')
    await CreationConstraint.create(novel_id=conversation.novel_id, source_message=source, fingerprint='warm',
        content='灯光必须温暖', source_quote='更温暖', scope={'kind': 'project'})
    calls = 0

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            payload = next(json.loads(part.content) for message in messages for part in message.parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, str) and 'preflight_context' in part.content)
            context = payload['preflight_context']
            assert context['selected_objects'][0]['id'] == request.targets[0].id
            assert context['creation_contexts'][0]['constraints_for_new_objects'][0]['content'] == '灯光必须温暖'
            yield {0: DeltaToolCall(name='apply_creation_changes', tool_call_id='write-after-preflight', json_args=json.dumps({
                'operations': [{'operation': 'update_scene', 'scene_id': request.targets[0].id,
                    'fields': {'prompt': '空站台中央洒下温暖灯光。'}}]}))}
        else:
            yield '已保存灯光修改。'

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *_: FunctionModel(stream_function=respond))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert calls == 2
    native = (await AgentMessage.get(task=task, role='assistant')).native_messages
    errors = [part.get('content') for message in native for part in message.get('parts', []) if part.get('part_kind') == 'retry-prompt']
    assert await PromptChange.filter(task=task).count() == 1, errors


@pytest.mark.asyncio
async def test_resumed_planning_replays_completed_model_output_without_a_second_call(monkeypatch):
    from uuid import uuid4
    from auth.deps import AuthContext
    from schemas.creation_agent import AgentRunRequest
    from schemas.agent_workflow import CompletePrompt
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from services.creation_agent.sessions import agent_sessions
    from services.creation_agent.skill_execution import SkillExecution
    from test.test_services.test_creation_agent_sessions import session_fixture
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'targets': [], 'write_scope': 'chapter'})
    original = await agent_sessions.submit(conversation, request, AuthContext())
    await AiTask.filter(id=original.id).update(status=2)
    calls = []

    def respond(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'prompt': '已校验的内容'})])

    def model(*_):
        result = streaming_model(respond)
        result.client = AsyncMock()
        return result

    monkeypatch.setattr('services.creation_agent.handler.configured_model', model)
    execution = SkillExecution(original.request_params, await AgentMessage.get(task=original, role='assistant'), AsyncMock())
    first = await execution.generate('structured', {'segment': 'page1'}, CompletePrompt)
    await AiTask.filter(id=original.id).update(status=4)
    resumed = await agent_sessions.submit(conversation, AgentRunRequest(request_id=uuid4(), message='继续',
        resume_from_task_id=original.id), AuthContext())
    await AiTask.filter(id=resumed.id).update(status=2)
    execution = SkillExecution(resumed.request_params, await AgentMessage.get(task=resumed, role='assistant'), AsyncMock())
    replay = await execution.generate('structured', {'segment': 'page1'}, CompletePrompt)
    assert replay == first and len(calls) == 1


@pytest.mark.asyncio
async def test_restart_keeps_paid_chat_transcript_and_never_reauthors_saved_writes():
    from auth.deps import AuthContext
    from services.creation_agent.sessions import agent_sessions
    from services.creation_agent.recovery import ProductionRecovery
    from test.test_services.test_creation_agent_sessions import session_fixture
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    await AiTask.filter(id=task.id).update(status=2)
    message = await AgentMessage.get(task=task, role='assistant')
    message.usage = {'calls': [{'phase': 'main', 'status': 'completed', 'usage_reported': True}]}
    message.native_messages = [{'kind': 'response', 'parts': [{'part_kind': 'text', 'content': '合成已保存记录'}]}]
    await message.save()
    await ProductionRecovery().recover()
    await task.refresh_from_db()
    await message.refresh_from_db()
    assert task.status == 4 and task.stage == 'needs_review'
    assert message.native_messages[0]['parts'][0]['content'] == '合成已保存记录'


@pytest.mark.asyncio
async def test_storyboard_draft_renders_canonical_sections_with_default_strategy(monkeypatch):
    from schemas.creation_agent import AgentTarget
    from schemas.agent_workflow import StructuredSkillStoryboard
    from services.creation_agent.object_drafts import revise_object
    from services.creation_agent.skill_execution import SkillExecution, current_execution
    from test.test_services.test_asset_design_instructions import synthetic_snapshot
    from test.test_services.test_prompt_language import _shot
    service, scene, _, _, task = await crud()
    execution = SkillExecution({'task_id': str(task.id), 'prompt_language': 'zh',
        'skill_snapshot': synthetic_snapshot().model_dump()}, None, AsyncMock())

    async def generate(skill, facts, output_type, **kwargs):
        assert skill == 'storyboard' and facts['shot_duration_range'] == [6, 6]
        shot = _shot().model_dump()
        shot.update(duration='6s', visual_prose='老人在晨雾中漫步。', actions=['0s-6s: 老人沿小路缓步前行。'])
        return StructuredSkillStoryboard.model_validate({'shots': [shot]})

    monkeypatch.setattr(execution, 'generate', AsyncMock(side_effect=generate))
    token = current_execution.set(execution)
    try:
        await revise_object(service, execution, AgentTarget(kind='scene', id=scene.id), '老人慢慢行走，保留时长', 'full-scene')
    finally:
        current_execution.reset(token)
    await scene.refresh_from_db()
    assert '【禁止项】' in scene.prompt and '【全局前置条件】' in scene.prompt
    assert '镜头时长:6s' in scene.prompt and '老人在晨雾中漫步' in scene.prompt


@pytest.mark.asyncio
@pytest.mark.parametrize('remake_truncated', [False, True])
async def test_summary_output_limit_does_not_block_main_tool_repair(remake_truncated):
    from pydantic_ai.messages import ModelRequest, RetryPromptPart
    from pydantic_ai.models.function import FunctionModel
    from services.creation_agent.model_boundary import RecordedAgentModel
    from models.creation_agent import AgentConversation
    from pydantic_ai.models import ModelRequestParameters
    changes, _, _, _, task = await crud()
    conversation = await AgentConversation.create(novel_id=changes.novel_id)
    message = await AgentMessage.create(conversation=conversation, task=task, request_id=task.id, request_hash='summary-limit', role='assistant')
    model = RecordedAgentModel(FunctionModel(lambda messages, info: None), message=message, before_request=AsyncMock(), max_characters=None, repair_root=str(task.id))
    model.calls = [{'phase': 'main', 'finish_reason': 'tool_call', 'usage_reported': True}, {'phase': 'summary', 'finish_reason': 'length', 'usage_reported': True}]
    if remake_truncated:
        model.stage = 'remake'
        model.calls[0]['finish_reason'] = 'length'
    await model._begin([ModelRequest(parts=[RetryPromptPart('invalid tool arguments', tool_name='link_scene_references', tool_call_id='repair')])], ModelRequestParameters())
    repair = await AgentOperation.get(task=task, key='recovery:repair')
    assert repair.state == 'completed'


@pytest.mark.asyncio
async def test_remake_repairs_two_validation_failures_independently():
    from services.creation_agent.reliability import claim_repair, RepairExhausted
    task = await AiTask.create(task_type=7, status=2)
    await claim_repair(task.id, [{'code': 'missing'}], attempts=2)
    await claim_repair(task.id, [{'code': 'tool_validation'}], attempts=2)
    with pytest.raises(RepairExhausted):
        await claim_repair(task.id, [{'code': 'tool_validation'}], attempts=2)
