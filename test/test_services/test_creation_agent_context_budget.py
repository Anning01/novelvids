import json
from uuid import uuid4
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.exceptions import ModelHTTPError

from models.ai_task import AiTask
from models.creation_agent import AgentMessage, AgentContextCheckpoint
from schemas.creation_agent import AgentConfiguration, AgentTarget
from schemas.creation_objects import CreationChangeSet, PromptReplacement
from services.creation_agent.context_budget import ContextBudget, wire_size
from services.creation_agent.history import prepare_history
from services.creation_agent.model_boundary import RecordedAgentModel
from services.creation_agent.prompt_edits import replace_prompt_fragments
from services.creation_agent.retrieval import read_history
from services.creation_agent.runtime import CreationAgentDeps, _narrow_change_schema, creation_agent
from services.creation_agent.tools import PromptEditService
from test.test_services.test_creation_agent_sessions import session_fixture
from test.test_services.test_creation_agent_crud import crud


async def message_fixture():
    conversation, _, _ = await session_fixture()
    task = await AiTask.create(task_type=7, status=3)
    assistant = await AgentMessage.create(conversation=conversation, task=task, role='assistant',
        request_id=uuid4(), request_hash='budget')
    return conversation, assistant


def test_wire_budget_counts_instructions_once_not_native_metadata():
    messages = [ModelRequest(parts=[UserPromptPart('你好')], instructions='固定规则' * 20),
                ModelResponse(parts=[TextPart('你好')]),
                ModelRequest(parts=[UserPromptPart('继续')], instructions='固定规则' * 20)]
    report = wire_size(messages, ModelRequestParameters())
    assert report['instructions'] == 80
    assert report['total_characters'] < 180


def test_operation_schema_only_keeps_requested_write_capability():
    full = CreationChangeSet.model_json_schema()
    narrowed = _narrow_change_schema(full, {'update_scene'})

    assert set(narrowed['$defs']) == {
        'PromptReplacement', 'SceneContentChanges', 'SceneFields',
        'ScenePromptSegment', 'UpdateScene',
    }
    assert narrowed['properties']['operations']['items']['discriminator']['mapping'] == {
        'update_scene': '#/$defs/UpdateScene',
    }
    assert len(json.dumps(narrowed, ensure_ascii=False)) < len(json.dumps(full, ensure_ascii=False)) * 0.65


@pytest.mark.asyncio
async def test_offloaded_read_is_recoverable_private_and_keeps_constraints():
    conversation, assistant = await message_fixture()
    payload = {'prompt': '雨夜站台' * 4000, 'constraints': [{'content': '女主灰色风衣', 'scope': {'kind': 'project'}}]}
    messages = [ModelRequest(parts=[UserPromptPart('只改光线')]),
        ModelResponse(parts=[ToolCallPart('read_creation_objects', {}, tool_call_id='read')]),
        ModelRequest(parts=[ToolReturnPart('read_creation_objects', payload, tool_call_id='read')]),
        ModelResponse(parts=[ToolCallPart('query_creation_objects', {}, tool_call_id='query')]),
        ModelRequest(parts=[ToolReturnPart('query_creation_objects', {'items': []}, tool_call_id='query')])]
    budget = ContextBudget(AgentConfiguration(max_context_characters=6000, working_input_tokens=2000), assistant)
    compacted = await budget.prepare(messages, ModelRequestParameters())
    archived = compacted[2].parts[0].content
    assert archived['constraints'] == payload['constraints']
    assert wire_size(compacted, ModelRequestParameters())['total_characters'] < 6000
    page = await read_history(assistant, archive_id=archived['archive_ref'], limit=300)
    assert len(page['content']) == 300 and page['next_offset'] == 300
    from models.creation_agent import AgentConversation
    other_conversation = await AgentConversation.create(novel_id=conversation.novel_id)
    other = SimpleNamespace(conversation_id=other_conversation.id, id=assistant.id)
    with pytest.raises(ValueError, match='当前会话'):
        await read_history(other, archive_id=archived['archive_ref'])
    assert messages[2].parts[0].content == payload
    await budget.prepare(messages, ModelRequestParameters())
    assert await AgentContextCheckpoint.filter(conversation=conversation, kind='tool_archive').count() == 1


@pytest.mark.asyncio
async def test_hundred_turn_backlog_is_bounded_even_when_summary_fails():
    conversation, current = await message_fixture()
    # Insert a backlog before a new current message. No live provider calls.
    for number in range(100):
        task = await AiTask.create(task_type=7, status=3)
        rid = uuid4()
        await AgentMessage.create(conversation=conversation, task=task, role='user', request_id=rid,
            request_hash='load', content=f'第{number}轮：只调整当前镜头光线')
        await AgentMessage.create(conversation=conversation, task=task, role='assistant', request_id=rid,
            request_hash='load', content=f'第{number}轮已保存', native_messages=[
                {'kind': 'response', 'parts': [{'part_kind': 'text', 'content': '完整镜头描述' * 3000}]}])
    task = await AiTask.create(task_type=7)
    current = await AgentMessage.create(conversation=conversation, task=task, role='assistant', request_id=uuid4(), request_hash='now')
    def unavailable(messages, info):
        raise RuntimeError('summary unavailable')
    history = await prepare_history(conversation, current, AgentConfiguration(max_context_characters=8000), FunctionModel(unavailable))
    assert len(str(history)) < 8000
    assert '第99轮' in str(history)
    assert await AgentMessage.filter(conversation=conversation).count() == 202
    assert await AgentContextCheckpoint.filter(conversation=conversation, kind='extractive_summary').exists()
    recovered = await read_history(current, query='第50轮')
    assert len(recovered['items']) == 2


@pytest.mark.asyncio
async def test_provider_context_rejection_retries_once_without_running_tools():
    _, assistant = await message_fixture()
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ModelHTTPError(400, 'model', {'error': {'code': 'context_length_exceeded'}})
        return ModelResponse(parts=[TextPart('已恢复')])
    async def authorize(): pass
    model = RecordedAgentModel(FunctionModel(respond), message=assistant, before_request=authorize, max_characters=64000)
    response = await model.request([ModelRequest(parts=[UserPromptPart('你好')])], None, ModelRequestParameters())
    assert response.parts[0].content == '已恢复' and calls == 2
    assert model.overflow_retried
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_small_talk_uses_one_light_request_without_business_context():
    service, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=service.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = []
    def respond(messages, info):
        calls.append(messages)
        assert {t.name for t in info.function_tools} == {
            'get_creation_context', 'read_creation_history', 'patch_creation_prompts',
        }
        assert not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
        return ModelResponse(parts=[TextPart('可以使用中文提示词。')])
    result = await creation_agent.run('提示词可以使用中文吗', model=FunctionModel(respond),
        deps=CreationAgentDeps(service=legacy, changes=service, context={'chapter': {'content': '不应发送的正文' * 10000}}))
    assert len(calls) == 1 and '中文' in result.output
    assert '不应发送的正文' not in str(calls)


@pytest.mark.asyncio
async def test_exact_patch_preserves_complete_scene_and_undo():
    service, scene, _, _, _ = await crud()
    scene.prompt = '【镜头1 · 6s】\n冷光洒在站台。\n环境音：细雨。'
    await scene.save()
    await service.read([AgentTarget(kind='scene', id=scene.id)])
    receipt = await service.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_scene', 'scene_id': scene.id,
        'fields': {'prompt_replacements': [{'old': '冷光', 'new': '暖光'}]},
    }]}), tool_call_id='patch')
    await scene.refresh_from_db()
    assert scene.prompt == '【镜头1 · 6s】\n暖光洒在站台。\n环境音：细雨。'
    assert receipt.changes[0]['before']['prompt'].startswith('【镜头1')
    await service.undo(receipt.id)
    await scene.refresh_from_db()
    assert '冷光' in scene.prompt


def test_patch_rejects_ambiguous_overlapping_and_mixed_modes():
    with pytest.raises(ValueError, match='唯一匹配'):
        replace_prompt_fragments('雨中雨', [PromptReplacement(old='雨', new='雪')])
    with pytest.raises(ValueError, match='重叠'):
        replace_prompt_fragments('冷光站台', [PromptReplacement(old='冷光', new='暖'), PromptReplacement(old='光站台', new='光屋')])
    with pytest.raises(ValidationError):
        CreationChangeSet.model_validate({'operations': [{'operation': 'update_scene', 'scene_id': 1,
            'fields': {'prompt': '完整内容', 'prompt_replacements': [{'old': '雨', 'new': '雪'}]}}]})
