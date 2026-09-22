from decimal import Decimal
from uuid import uuid4

import pytest

from models.ai_task import AiTask
from models.creation_agent import AgentConversation, AgentMessage
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.billing import aggregation
from utils.enums import AiTaskTypeEnum
from utils.page import QueryParams


async def agent_record(conversation, cost, *, user_id=1, team_id=1, model='first', status=3, currency='CNY'):
    task = await AiTask.create(task_type=AiTaskTypeEnum.creation_agent.value, status=status,
                               request_params={'novel_id': conversation.novel_id})
    await AgentMessage.create(conversation=conversation, task=task, role='assistant', request_id=uuid4(),
                              request_hash='test', content='私密会话内容不能出现在成本流水')
    return await ModelUsageRecord.create(novel_id=conversation.novel_id, task_type=AiTaskTypeEnum.creation_agent.value,
        billing_type='text', ai_task_id=task.id, model=model, model_name=model, cost=Decimal(cost),
        usage={'input_tokens': 100, 'output_tokens': 20, 'requests': 3}, duration_seconds=2,
        status=status, team_id=team_id, user_id=user_id, currency=currency,
        pricing_snapshot={'discount': 0.5}, cost_source='team_key' if model == 'second' else 'balance')


@pytest.mark.asyncio
async def test_conversation_groups_before_pagination_and_keeps_exact_cost_and_usage():
    novel = await Novel.create(name='测试项目')
    conversation = await AgentConversation.create(novel=novel)
    first = await agent_record(conversation, '0.100001')
    normal = await ModelUsageRecord.create(novel_id=novel.id, task_type=4, billing_type='video', model='video', cost=2)
    latest = await agent_record(conversation, '0.200002', model='second', status=4)
    page = await aggregation.list_records(QueryParams(page=1, page_size=1))
    assert page['pagination']['total'] == 2 and page['pagination']['pages'] == 2
    group = page['items'][0]
    assert group.id == latest.id and group.conversation_id == conversation.id
    assert group.record_kind == 'agent_conversation'
    assert group.cost == 0.300003 and group.usage['input_tokens'] == 200
    assert group.usage['requests'] == 6 and group.turn_count == 2 and group.record_count == 2
    assert group.pricing_snapshot is None and group.cost_source == 'mixed'
    assert set(group.statuses) == {3, 4} and group.duration_seconds == 4
    assert group.model_name == 'first、second'
    assert '私密会话' not in group.model_dump_json()
    second = await aggregation.list_records(QueryParams(page=2, page_size=1))
    assert second['items'][0].id == normal.id
    assert await ModelUsageRecord.all().count() == 3
    assert (await ModelUsageRecord.get(id=first.id)).cost == Decimal('0.100001')


@pytest.mark.asyncio
async def test_filters_scope_and_deleted_conversations_do_not_drop_or_mix_costs():
    novel = await Novel.create(name='项目')
    conversation = await AgentConversation.create(novel=novel)
    other = await AgentConversation.create(novel=novel)
    await agent_record(conversation, '1', user_id=1)
    await agent_record(conversation, '2', user_id=2)
    await agent_record(other, '4', team_id=2)
    scoped = await aggregation.list_records(QueryParams(page=1, page_size=10), team_id=1, user_id=1)
    assert len(scoped['items']) == 1 and scoped['items'][0].cost == 1
    assert scoped['items'][0].turn_count == 1
    filtered = await aggregation.list_records(QueryParams(page=1, page_size=10, filters={'novel_id': novel.id}), team_id=1)
    assert len(filtered['items']) == 1 and filtered['items'][0].cost == 3
    from datetime import datetime, timezone
    conversation.deleted_at = datetime.now(timezone.utc)
    await conversation.save()
    assert (await aggregation.list_records(QueryParams(page=1, page_size=10), team_id=1))['items'][0].cost == 3


@pytest.mark.asyncio
async def test_missing_conversation_and_different_currencies_stay_separate():
    novel = await Novel.create(name='项目')
    conversation = await AgentConversation.create(novel=novel)
    await agent_record(conversation, '1')
    await agent_record(conversation, '2', currency='USD')
    orphan = await ModelUsageRecord.create(novel_id=novel.id, task_type=7, billing_type='text', model='old', cost=3)
    result = await aggregation.list_records(QueryParams(page=1, page_size=10))
    assert result['pagination']['total'] == 3
    assert result['items'][0].id == orphan.id and result['items'][0].record_kind == 'call'
    assert {item.currency for item in result['items']} == {'CNY', 'USD'}


@pytest.mark.asyncio
async def test_details_are_paged_original_records_and_respect_scope_and_filters():
    novel = await Novel.create(name='项目')
    conversation = await AgentConversation.create(novel=novel)
    first = await agent_record(conversation, '1', user_id=1, status=3)
    second = await agent_record(conversation, '2', user_id=2, status=4)
    details = await aggregation.list_records(QueryParams(page=1, page_size=1), team_id=1, record_id=first.id)
    assert details['pagination']['total'] == 2
    assert details['items'][0].id == second.id and details['items'][0].record_kind == 'call'
    assert details['items'][0].pricing_snapshot == {'discount': 0.5}
    own = await aggregation.list_records(QueryParams(page=1, page_size=10), team_id=1, user_id=1, record_id=first.id)
    assert [item.id for item in own['items']] == [first.id]
    with pytest.raises(LookupError):
        await aggregation.list_records(QueryParams(page=1, page_size=10), team_id=1, user_id=1, record_id=second.id)
    filtered = await aggregation.list_records(QueryParams(page=1, page_size=10, filters={'status': 4}), team_id=1)
    assert len(filtered['items']) == 1 and filtered['items'][0].cost == 2
    assert (await aggregation.summary())['total_cost'] == 3


@pytest.mark.asyncio
async def test_same_run_multiple_records_counts_one_turn_and_never_crosses_projects():
    novel = await Novel.create(name='项目一')
    other = await Novel.create(name='项目二')
    conversation = await AgentConversation.create(novel=novel)
    first = await agent_record(conversation, '1')
    await ModelUsageRecord.create(novel_id=novel.id, task_type=7, billing_type='text', ai_task_id=first.ai_task_id,
        model='first', cost=2, currency='CNY', team_id=1, duration_seconds=None)
    await ModelUsageRecord.create(novel_id=other.id, task_type=7, billing_type='text', ai_task_id=first.ai_task_id,
        model='first', cost=4, currency='CNY', team_id=1)
    result = await aggregation.list_records(QueryParams(page=1, page_size=10), team_id=1)
    assert result['pagination']['total'] == 2
    group = next(item for item in result['items'] if item.record_kind == 'agent_conversation')
    assert group.turn_count == 1 and group.record_count == 2 and group.cost == 3
    assert group.duration_seconds is None
