import json

import pytest
from tortoise import Tortoise
from pydantic_ai.models.function import FunctionModel, DeltaToolCall

from auth.deps import AuthContext
from models.ai_task import AiTask
from models.creation_agent import AgentEvent, AgentMessage
from services.ai_task_executor import AiTaskExecutor
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.handler import CreationAgentTaskHandler
from services.creation_agent.sessions import agent_sessions
from test.query_counting import count_queries
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_handler_appends_events_and_never_rewrites_the_message_event_array(monkeypatch):
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield 'Internal planning: inspect scene_id and tool parameters.'
            yield {0: DeltaToolCall(name='get_creation_context', json_args='{}', tool_call_id='read')}
        elif calls == 2:
            yield {0: DeltaToolCall(name='update_storyboard_prompt', tool_call_id='write', json_args=json.dumps({'edits': [{
                'scene_id': request.targets[0].id, 'legacy_prompt': '暖光洒在空站台上。',
            }]}, ensure_ascii=False))}
        else:
            yield '已把灯光调暖。'

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    async with count_queries() as statements:
        await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value, task.error_message
    assistant = await AgentMessage.get(task=task, role='assistant')
    events = await agent_event_log.load(assistant)
    assert events[-1]['type'] == 'RUN_FINISHED'
    assert 'Internal planning' not in str(events)
    # 追加写：消息行不再承载整个事件数组
    assert assistant.events == []
    sequences = [row['seq'] for row in await AgentEvent.filter(message_id=assistant.id).order_by('seq').values('seq')]
    assert sequences == list(range(len(events)))
    inserts = [item for item in statements if item.lstrip().upper().startswith('INSERT') and 'creation_agent_events' in item]
    assert len(inserts) >= 2
    rewrites = [item for item in statements if item.lstrip().upper().startswith('UPDATE') and '"events"' in item.split('WHERE')[0]]
    assert not rewrites, rewrites


@pytest.mark.asyncio
async def test_append_is_one_bounded_write_regardless_of_existing_log_size():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    assistant = await AgentMessage.get(task=task, role='assistant')
    await AgentEvent.bulk_create([AgentEvent(message_id=assistant.id, seq=index, event={'type': 'TEXT_MESSAGE_CONTENT', 'delta': 'x'})
                                  for index in range(500)])
    assert await agent_event_log.start(assistant) == 500
    async with count_queries() as statements:
        next_seq = await agent_event_log.append(assistant.id, [{'type': 'TEXT_MESSAGE_START'}, {'type': 'RUN_FINISHED'}], 500)
    assert next_seq == 502
    assert len(statements) == 1, statements
    events = await agent_event_log.load(assistant)
    assert len(events) == 502 and events[-1]['type'] == 'RUN_FINISHED'


@pytest.mark.asyncio
async def test_legacy_json_events_stay_readable_and_are_adopted_once():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    legacy = [{'type': 'RUN_STARTED', 'threadId': str(conversation.id), 'runId': str(task.id)},
              {'type': 'TEXT_MESSAGE_START', 'messageId': 'm', 'role': 'assistant'},
              {'type': 'RUN_FINISHED', 'threadId': str(conversation.id), 'runId': str(task.id)}]
    await AgentMessage.filter(task=task, role='assistant').update(events=legacy)
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert await agent_event_log.load(assistant) == legacy
    assert await agent_event_log.page(assistant, 1, 2) == legacy[1:]
    assert await agent_event_log.last(assistant) == legacy[-1]
    assert await agent_event_log.start(assistant) == 3
    assert await agent_event_log.start(assistant) == 3
    assert await AgentEvent.filter(message_id=assistant.id).count() == 3
    assert await agent_event_log.load(assistant) == legacy
    await Tortoise.generate_schemas(safe=True)
    assert await AgentEvent.filter(message_id=assistant.id).count() == 3


@pytest.mark.asyncio
async def test_load_many_reads_table_logs_in_one_query_and_falls_back_to_legacy():
    conversation, _, _ = await session_fixture()
    messages = []
    for index in range(3):
        task = await AiTask.create(task_type=1, status=TaskStatusEnum.completed.value)
        messages.append(await AgentMessage.create(conversation=conversation, task=task, request_id=task.id,
            request_hash=f'h{index}', role='assistant',
            events=[{'type': 'RUN_STARTED'}] if index == 2 else []))
    await agent_event_log.append(messages[0].id, [{'type': 'RUN_STARTED'}, {'type': 'RUN_FINISHED'}], 0)
    await agent_event_log.append(messages[1].id, [{'type': 'RUN_STARTED'}], 0)
    async with count_queries() as statements:
        loaded = await agent_event_log.load_many(messages)
    assert len(statements) == 1, statements
    assert loaded[messages[0].id] == [{'type': 'RUN_STARTED'}, {'type': 'RUN_FINISHED'}]
    assert loaded[messages[1].id] == [{'type': 'RUN_STARTED'}]
    assert loaded[messages[2].id] == [{'type': 'RUN_STARTED'}]
