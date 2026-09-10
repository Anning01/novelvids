import json

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart, TextPart, RetryPromptPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from models.asset import Asset
from models.creation_agent import PromptChange
from services.creation_agent.runtime import CreationAgentDeps, creation_agent
from test.test_services.test_creation_agent_crud import crud
from services.creation_agent.tools import PromptEditService


@pytest.mark.asyncio
async def test_crud_model_discovers_then_creates_without_manual_selection():
    changes, scene, asset, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        names = {tool.name for tool in info.function_tools}
        assert names == {'get_creation_context', 'query_creation_objects', 'read_creation_objects', 'apply_creation_changes', 'undo_creation_change'}
        assert 'expected_version' not in json.dumps([t.parameters_json_schema for t in info.function_tools])
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='context')])
        if calls == 2:
            return ModelResponse(parts=[ToolCallPart('query_creation_objects', {'query': {'kind': 'asset'}}, tool_call_id='query')])
        if calls == 3:
            query = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)][-1]
            assert query.content['items'][0]['id'] == asset.id
            return ModelResponse(parts=[ToolCallPart('apply_creation_changes', {'operations': [
                {'operation': 'create_setting', 'client_ref': 'umbrella', 'asset_type': 3, 'name': '红伞',
                 'description': '红色长柄伞', 'prompt': '红色布面长柄伞，木柄，完整展示'}]}, tool_call_id='create')])
        saved = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)][-1]
        assert 'changes' in saved.content, [part.content for message in messages for part in message.parts if isinstance(part, RetryPromptPart)]
        assert saved.content['changes'][0]['operation'] == 'create'
        return ModelResponse(parts=[TextPart('已为本章新增红伞设定。')])

    result = await creation_agent.run('查询本章设定，再增加一把红伞。', model=FunctionModel(model),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}), usage_limits=UsageLimits(request_limit=5))
    assert result.output == '已为本章新增红伞设定。'
    assert await Asset.filter(canonical_name='红伞', novel_id=changes.novel_id).exists()
    assert await PromptChange.filter(task_id=task.id).count() == 1


@pytest.mark.asyncio
async def test_final_reply_uses_human_categories_instead_of_schema_fields():
    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[TextPart('人物（asset_type 1）：林夏')])
        assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        return ModelResponse(parts=[TextPart('本章人物是林夏。')])

    result = await creation_agent.run('本章有哪些人物？', model=FunctionModel(model),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}), usage_limits=UsageLimits(request_limit=2))
    assert result.output == '本章人物是林夏。'
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
async def test_model_can_find_and_undo_deleted_object_after_native_history_is_compressed():
    from models.creation_agent import AgentConversation, AgentMessage
    from models.scene import Scene
    from schemas.creation_objects import CreationChangeSet

    changes, scene, _, _, task = await crud()
    saved = await changes.apply(CreationChangeSet.model_validate({'operations': [
        {'operation': 'delete', 'target': {'kind': 'scene', 'id': scene.id}},
    ]}), tool_call_id='remove')
    conversation = await AgentConversation.create(novel_id=changes.novel_id)
    source = await AgentMessage.create(conversation=conversation, task=task, role='user',
        request_id=task.id, request_hash='source', run_input=changes.request.model_dump(mode='json'))
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='context')])
        receipt = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)][-1].content
        if calls == 2:
            candidates = receipt['recent_changes']['items']
            assert receipt['recent_changes']['total'] == 1
            assert candidates[0]['change_id'] == saved.id
            assert candidates[0]['changes'][0]['operation'] == 'delete'
            assert 'prompt' not in json.dumps(candidates)
            return ModelResponse(parts=[ToolCallPart('undo_creation_change', {'change_id': candidates[0]['change_id']}, tool_call_id='restore')])
        assert receipt['status'] == 'reverted'
        return ModelResponse(parts=[TextPart('已恢复刚才移除的分镜。')])

    result = await creation_agent.run('恢复刚才删除的分镜。', model=FunctionModel(model), message_history=[],
        deps=CreationAgentDeps(service=legacy, changes=changes, context={'summary': '此前删除了分镜'}, source_message=source),
        usage_limits=UsageLimits(request_limit=3))
    assert result.output == '已恢复刚才移除的分镜。'
    assert await Scene.filter(id=scene.id).exists()
