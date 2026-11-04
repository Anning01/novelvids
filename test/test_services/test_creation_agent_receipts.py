from uuid import UUID, uuid4, uuid5

import pytest

from auth.deps import AuthContext
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from services.creation_agent.authorization import pending_production, pending_productions
from services.creation_agent.receipts import production_receipts, production_receipts_for, usage_summaries, usage_summary
from services.creation_agent.sessions import agent_sessions
from test.query_counting import count_queries
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import TaskStatusEnum


@pytest.mark.asyncio
async def test_usage_summaries_aggregate_child_runs_in_one_load():
    conversation, request, _ = await session_fixture()
    parent_task = await agent_sessions.submit(conversation, request, AuthContext())
    await AgentMessage.filter(task=parent_task, role='assistant').update(
        usage={'requests': 1, 'input_tokens': 10, 'output_tokens': 5})
    parent = await AgentMessage.get(task=parent_task, role='assistant')
    child_task = await AiTask.create(task_type=7, status=TaskStatusEnum.completed.value,
        request_params={'parent_task_id': str(parent_task.id)})
    await AgentMessage.create(conversation=conversation, task=child_task, request_id=child_task.id,
        request_hash='child', role='assistant',
        usage={'requests': 2, 'input_tokens': 100, 'output_tokens': 20, 'missing_usage': True})
    async with count_queries() as statements:
        summaries = await usage_summaries([parent])
    assert len(statements) == 1, statements
    assert summaries[parent.id] == {'requests': 3, 'input_tokens': 110, 'output_tokens': 25, 'cache_read_tokens': 0,
                                     'summary_requests': 0, 'missing_usage': True}
    assert await usage_summary(parent) == summaries[parent.id]


@pytest.mark.asyncio
async def test_production_receipts_batch_matches_single_task_projection():
    parent_task = await AiTask.create(task_type=7, status=TaskStatusEnum.completed.value,
        request_params={'workflow_version': 'agent-skills-v1', 'operation': 'story'})
    plain_task = await AiTask.create(task_type=1, status=TaskStatusEnum.completed.value)
    story_task = await AiTask.create(task_type=3, status=TaskStatusEnum.completed.value,
        request_params={'workflow_version': 'agent-skills-v1'})
    child_task = await AiTask.create(task_type=1, status=TaskStatusEnum.completed.value)
    await AgentOperation.create(task=parent_task, key='submit:story', state='completed',
        result={'task_id': str(child_task.id)})
    async with count_queries() as statements:
        receipts = await production_receipts_for([parent_task, plain_task, story_task])
    assert len(statements) == 2, statements
    assert [item['operation'] for item in receipts[str(parent_task.id)]] == ['assets']
    assert [item['operation'] for item in receipts[str(story_task.id)]] == ['storyboard']
    assert receipts[str(plain_task.id)] == []
    assert receipts[str(parent_task.id)] == await production_receipts(parent_task.id)
    assert receipts[str(story_task.id)] == await production_receipts(story_task.id)
    assert receipts[str(plain_task.id)] == await production_receipts(plain_task.id)


@pytest.mark.asyncio
async def test_pending_productions_gate_uses_one_query_and_matches_single_entry():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    async with count_queries() as statements:
        pending = await pending_productions([task])
    assert pending == {str(task.id): None}
    assert len(statements) == 1, statements
    assert await pending_production(task.id) is None


@pytest.mark.asyncio
async def test_pending_productions_reports_proposals_until_confirmation_exists():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    user = await AgentMessage.get(task=task, role='user')
    proposal = {'operation': 'video', 'target_id': request.targets[0].id, 'request_id': str(uuid4())}
    await AgentMessage.filter(id=user.id).update(run_input={**user.run_input, 'production_proposals': [proposal]})
    pending = await pending_productions([task])
    assert pending[str(task.id)]['labels'][0]['operation'] == 'video'
    assert pending[str(task.id)]['intents'] == [proposal]
    assert pending[str(task.id)]['confirmation_request_id'] == str(uuid5(UUID(str(task.id)), 'production-confirmation'))
    assert await pending_production(task.id) == pending[str(task.id)]
    confirmation_id = uuid5(UUID(str(task.id)), 'production-confirmation')
    other = await AiTask.create(task_type=7, status=TaskStatusEnum.completed.value)
    await AgentMessage.create(conversation=conversation, task=other, request_id=confirmation_id,
        request_hash='confirm', role='user')
    assert await pending_productions([task]) == {str(task.id): None}
    assert await pending_production(task.id) is None
