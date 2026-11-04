import json

import pytest

from auth.deps import AuthContext
from controllers.creation_agent import creation_agent_controller
from models.ai_task import AiTask
from models.creation_agent import AgentMessage, PromptChange
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.sessions import agent_sessions
from test.query_counting import count_queries
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import TaskStatusEnum


def _receipt_events() -> list[dict]:
    return [
        {'type': 'TOOL_CALL_START', 'toolCallId': 'query', 'toolCallName': 'query_creation_objects'},
        {'type': 'TOOL_CALL_RESULT', 'toolCallId': 'query', 'content': json.dumps(
            {'items': [{'kind': 'asset', 'id': 7, 'name': '蓝色雨衣'}], 'total': 1})},
    ]


async def _run_pair(conversation, index: int):
    task = await AiTask.create(task_type=1, status=TaskStatusEnum.completed.value)
    await AgentMessage.create(conversation=conversation, task=task, role='user',
        request_id=task.id, request_hash=f'user-{index}')
    assistant = await AgentMessage.create(conversation=conversation, task=task, role='assistant',
        request_id=task.id, request_hash=f'assistant-{index}')
    await PromptChange.create(novel_id=conversation.novel_id, task=task,
        tool_call_id=f'change-{index}', request_hash=f'change-{index}', changes=[])
    await agent_event_log.append(assistant.id, _receipt_events(), 0)
    return task


@pytest.mark.asyncio
async def test_history_page_queries_do_not_grow_with_the_number_of_messages():
    small, _, _ = await session_fixture()
    large = await agent_sessions.create(small.novel_id, AuthContext())
    for index in range(3):
        await _run_pair(small, index)
    for index in range(12):
        await _run_pair(large, index)
    async with count_queries() as statements:
        small_page = await creation_agent_controller.messages(small.id, AuthContext(), None)
        small_queries = len(statements)
    async with count_queries() as statements:
        page = await creation_agent_controller.messages(large.id, AuthContext(), None)
        large_queries = len(statements)
    assistants = [item for item in page['items'] if item['role'] == 'assistant']
    assert len(assistants) == 12
    assert len(small_page['items']) == 6
    assert large_queries - small_queries <= 3, f'3 条消息 {small_queries} 次查询，12 条消息 {large_queries} 次查询：逐条查询没有收敛'
    assert all(len(item['changes']) == 1 for item in assistants)
    assert all(item['query_results'] == [{'items': [{'kind': 'asset', 'id': 7, 'name': '蓝色雨衣'}],
                                          'total': 1, 'has_more': False}] for item in assistants)
    assert all(item['pending_production'] is None and item['production'] == [] for item in assistants)


@pytest.mark.asyncio
async def test_snapshot_counts_legacy_event_arrays_and_replays_their_receipts():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    task.status = TaskStatusEnum.completed.value
    await task.save()
    legacy = [{'type': 'RUN_STARTED', 'threadId': str(conversation.id), 'runId': str(task.id)},
              *_receipt_events(),
              {'type': 'RUN_FINISHED', 'threadId': str(conversation.id), 'runId': str(task.id)}]
    await AgentMessage.filter(task=task, role='assistant').update(events=legacy)
    run = await creation_agent_controller.snapshot(task.id, AuthContext())
    assert run.event_count == 4
    assert run.pending_production is None and run.production == []
    assert len(run.query_results) == 1
    plain = run.query_results[0].model_dump()
    assert (plain['total'], plain['has_more']) == (1, False)
    assert [(item['kind'], item['id'], item['name']) for item in plain['items']] == [('asset', 7, '蓝色雨衣')]
