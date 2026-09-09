from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from auth.models import Team, TeamMember
from config import settings
from models.config import AiModelConfig
from models.creation_agent import AgentSettings
from models.novel import Novel
from schemas.creation_agent import AgentConfiguration, AgentRunRequest
from services.creation_agent.handler import authorize_run
from services.creation_agent.sessions import agent_sessions
from test.test_auth.test_team_scoping import _create_member, _login, _auth
from utils.enums import AiTaskTypeEnum


pytestmark = pytest.mark.skipif(not settings.AUTH_ENABLED, reason='本文件以 AUTH_ENABLED=true 验证真实角色/团队/会话隔离')


async def setup_private_run(client):
    team = await Team.create(name='创作测试团队', balance=Decimal('10'))
    owner, _ = await _create_member('agent-owner', team)
    teammate, _ = await _create_member('agent-teammate', team)
    membership = await TeamMember.get(user=owner, team=team)
    ctx = AuthContext(user=owner, membership=membership, team_id=team.id)
    novel = await Novel.create(name='私有对话项目', team_id=team.id, created_by=owner.id)
    await AiModelConfig.create(task_type=AiTaskTypeEnum.creation_agent.value, name='agent-test',
        base_url='https://example.invalid', model='fake-model', api_key='fake-key', is_active=True,
        supports_tool_calls=True, pricing={'type': 'text', 'input_price_per_1m': 1, 'output_price_per_1m': 2})
    await AgentSettings.create(id=1, configuration=AgentConfiguration(enabled=True).model_dump())
    conversation = await agent_sessions.create(novel.id, ctx)
    task = await agent_sessions.submit(conversation, AgentRunRequest(request_id=uuid4(), message='我的私有创作要求'), ctx)
    return team, owner, teammate, conversation, task, ctx


@pytest.mark.asyncio
async def test_same_team_member_cannot_read_private_chat_or_generic_task(client):
    _, owner, teammate, conversation, task, _ = await setup_private_run(client)
    owner_headers = _auth(await _login(client, owner.username))
    other_headers = _auth(await _login(client, teammate.username))
    response = await client.get(f'/api/creation-agent/conversations/{conversation.id}/messages', headers=owner_headers)
    assert response.json()['code'] == 0
    for url in (f'/api/creation-agent/conversations/{conversation.id}/messages',
                f'/api/creation-agent/runs/{task.id}', f'/api/task/{task.id}', f'/api/creation-agent/runs/{task.id}/events'):
        forbidden = await client.get(url, headers=other_headers)
        assert forbidden.json()['code'] == 404
        assert '私有创作要求' not in forbidden.text
    forbidden = await client.post(f'/api/task/{task.id}/cancel', headers=other_headers)
    assert forbidden.json()['code'] == 404


@pytest.mark.asyncio
async def test_viewer_cannot_submit_and_team_admin_cannot_change_global_settings(client, monkeypatch):
    team, _, _, conversation, _, _ = await setup_private_run(client)
    viewer, _ = await _create_member('agent-viewer', team, role='viewer')
    admin, _ = await _create_member('agent-admin', team, role='admin')
    headers = _auth(await _login(client, viewer.username))
    own = await client.post('/api/creation-agent/conversations', json={'novel_id': conversation.novel_id}, headers=headers)
    assert own.json()['code'] == 0
    runner = AsyncMock()
    monkeypatch.setattr('api.creation_agent.ai_task_executor.run', runner)
    denied = await client.post(f"/api/creation-agent/conversations/{own.json()['data']['id']}/runs",
        json={'request_id': str(uuid4()), 'message': '修改'}, headers=headers)
    assert denied.json()['code'] == 403
    runner.assert_not_awaited()
    denied = await client.put('/api/creation-agent/configuration', json=AgentConfiguration(enabled=True).model_dump(),
        headers=_auth(await _login(client, admin.username)))
    assert denied.json()['code'] == 403


@pytest.mark.asyncio
async def test_revoke_membership_after_submit_blocks_execution(client):
    team, owner, _, _, task, _ = await setup_private_run(client)
    await TeamMember.filter(team=team, user=owner).update(status=0)
    with pytest.raises(HTTPException) as denied:
        await authorize_run(task.request_params)
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_agent_billing_uses_existing_balance_path_once(client, monkeypatch):
    from pydantic_ai.models.function import FunctionModel
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from services.billing.recorder import record_ai_task_usage
    team, owner, _, _, task, _ = await setup_private_run(client)
    async def model(messages, info):
        yield '请选中需要修改的镜头。'
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db(); await team.refresh_from_db()
    balance = team.balance
    assert balance < Decimal('10')
    await record_ai_task_usage(task, task.response_data)
    await team.refresh_from_db()
    assert team.balance == balance
    member = await TeamMember.get(team=team, user=owner)
    assert member.total_cost == Decimal('10') - balance


@pytest.mark.asyncio
async def test_prompt_status_shares_creative_rule_but_not_private_source_and_rejects_other_team(client):
    from models.asset import Asset
    from models.creation_agent import AgentMessage, CreationConstraint
    team, owner, teammate, conversation, task, _ = await setup_private_run(client)
    asset = await Asset.create(novel_id=conversation.novel_id, canonical_name='合成人物', asset_type=1, base_traits='灰色衣服')
    source = await AgentMessage.get(task=task, role='user')
    await CreationConstraint.create(novel_id=conversation.novel_id, source_message=source, fingerprint='shared-status',
        content='保持低饱和写实风格', source_quote='私有来源不应出现在状态响应', scope={'kind': 'project'})
    url = f'/api/creation-agent/prompt-status?novel_id={conversation.novel_id}'
    body = {'targets': [{'kind': 'asset', 'id': asset.id}]}
    response = await client.post(url, json=body, headers=_auth(await _login(client, teammate.username)))
    assert response.json()['code'] == 0
    assert response.json()['data'][0]['pending_constraints'][0]['content'] == '保持低饱和写实风格'
    assert '私有' not in response.text and 'source_message' not in response.text
    other_team = await Team.create(name='外部状态团队')
    outsider, _ = await _create_member('status-outsider', other_team)
    denied = await client.post(url, json=body, headers=_auth(await _login(client, outsider.username)))
    assert denied.json()['code'] in (403, 404)
    assert '低饱和' not in denied.text
