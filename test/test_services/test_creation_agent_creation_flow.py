import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits

from models.asset import Asset
from schemas.creation_agent import AgentConfiguration
from services.creation_agent.runtime import CreationAgentDeps, creation_agent
from services.creation_agent.tools import PromptEditService
from services.creation_objects import CreationObjects, project_write
from test.test_services.test_creation_agent_crud import crud


@pytest.mark.asyncio
async def test_creation_is_available_on_first_request_and_saves_without_capability_handshake():
    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert {'create_creation_setting', 'query_creation_objects', 'read_creation_objects'} <= {t.name for t in info.function_tools}
            return ModelResponse(parts=[ToolCallPart('create_creation_setting', {
                'name': '胖子', 'asset_type': 1, 'description': '主角的死党', 'prompt': '圆脸少年，黑色短发，校服。',
            }, tool_call_id='create')])
        result = [p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]
        assert result['status'] == 'saved'
        return ModelResponse(parts=[TextPart('已创建胖子。')])
    await creation_agent.run('创建胖子，是主角的死党', model=FunctionModel(respond),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}), usage_limits=UsageLimits(request_limit=3))
    assert calls == 2 and await Asset.filter(novel_id=changes.novel_id, canonical_name='胖子').count() == 1


@pytest.mark.asyncio
async def test_archived_name_conflict_returns_actionable_result_without_query_loop():
    changes, _, asset, _, task = await crud()
    # An archived name cannot be silently reused or restored by a create request.
    async with project_write(changes.novel_id):
        await CreationObjects(changes.novel_id).archive('asset', asset.id)
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('create_creation_setting', {
                'name': asset.canonical_name, 'asset_type': 1, 'description': '新角色', 'prompt': '完整形象。',
            }, tool_call_id='create')])
        result = [p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart)][-1]
        assert result['status'] == 'needs_resolution' and result['existing']['state'] == 'archived'
        assert result['existing']['id'] == asset.id
        return ModelResponse(parts=[TextPart('有一个已移除的同名人物，可以换名创建。')])
    await creation_agent.run('创建角色', model=FunctionModel(respond),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}), usage_limits=UsageLimits(request_limit=3))
    assert calls == 2 and not await Asset.filter(id=asset.id).exists()


@pytest.mark.asyncio
async def test_last_request_is_reserved_for_a_reply_and_can_be_followed_by_another_turn():
    changes, _, _, _, task = await crud()
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='context')])
        assert not info.function_tools
        assert '本轮' in (info.instructions or '')
        return ModelResponse(parts=[TextPart('已读取上下文，可以继续描述要创建的人物。')])
    deps = CreationAgentDeps(service=legacy, changes=changes, context={}, limits=AgentConfiguration(request_limit=2))
    result = await creation_agent.run('先检查', model=FunctionModel(respond), deps=deps, usage_limits=UsageLimits(request_limit=2))
    assert calls == 2 and '继续' in result.output
    def next_turn(messages, info):
        assert 'create_creation_setting' in {t.name for t in info.function_tools}
        return ModelResponse(parts=[TextPart('收到新的要求。')])
    await creation_agent.run('继续', message_history=result.all_messages(), model=FunctionModel(next_turn),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}, limits=AgentConfiguration(request_limit=2)))


@pytest.mark.asyncio
async def test_named_query_reports_archived_name_without_exposing_removed_content():
    from schemas.creation_objects import CreationObjectQuery
    changes, _, asset, _, _ = await crud()
    async with project_write(changes.novel_id):
        await CreationObjects(changes.novel_id).archive('asset', asset.id)
    result = await changes.catalog.search(CreationObjectQuery(kind='asset', scope='project', search=asset.canonical_name))
    assert result['items'] == []
    assert result['archived_matches'] == [{'kind': 'asset', 'id': asset.id, 'name': asset.canonical_name, 'state': 'archived'}]
    assert 'base_traits' not in str(result) and 'prompt' not in str(result)


@pytest.mark.asyncio
async def test_direct_creation_cannot_bypass_read_only_scope():
    changes, _, _, _, task = await crud(scope='read_only')
    legacy = PromptEditService(novel_id=changes.novel_id, task_id=task.id, allowed_targets=set(), max_batch_size=8)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('create_creation_setting', {
                'name': '不应新增', 'asset_type': 1, 'description': '设定', 'prompt': '形象',
            }, tool_call_id='write')])
        return ModelResponse(parts=[TextPart('本轮只读，没有创建。')])
    await creation_agent.run('只查询', model=FunctionModel(respond),
        deps=CreationAgentDeps(service=legacy, changes=changes, context={}))
    assert not await Asset.filter(novel_id=changes.novel_id, canonical_name='不应新增').exists()
