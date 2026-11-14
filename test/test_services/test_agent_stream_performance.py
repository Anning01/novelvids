import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.function import FunctionModel, DeltaThinkingPart
from models.ai_task import AiTask
from models.creation_agent import AgentMessage, AgentEvent
from services.creation_agent.skill_stream import SkillRunActivity
from services.creation_agent.activity import activity_from_events
from services.creation_agent.event_log import AgentEventLog
from test.test_services.test_creation_agent_sessions import session_fixture


@pytest.mark.asyncio
async def test_thousands_of_thinking_chunks_store_linear_text_and_flush_on_completion():
    sink = SkillRunActivity(AsyncMock(task_id='child', conversation_id=1), 'owner')
    sink.publish_event = AsyncMock()
    async def respond(messages, info):
        for _ in range(4000):
            yield {0: DeltaThinkingPart(content='内容🐱')}
        yield 'done'
    with patch('services.creation_agent.skill_stream.monotonic', return_value=1000):
        await Agent().run('test', model=FunctionModel(stream_function=respond), event_stream_handler=sink)
    events = [call.args[0] for call in sink.publish_event.await_args_list]
    assert len(events) <= 4
    text_bytes = sum(len(event['value'].get('detail', '')) + len(event['value'].get('detail_delta', '')) for event in events)
    assert text_bytes == 2 * len('内容🐱' * 4000)
    assert activity_from_events(events[:-1], 2)[0]['detail'] == '内容🐱' * 4000
    assert activity_from_events(events, 3)[0]['status'] == 'completed'


@pytest.mark.asyncio
async def test_projection_skips_superseded_payloads_preserves_raw_history_and_invalidates_cache():
    conversation, _, _ = await session_fixture()
    task = await AiTask.create(task_type=7, status=2)
    message = await AgentMessage.create(conversation=conversation, task=task, request_id=uuid4(), request_hash='performance', role='assistant')
    def state(detail):
        return {'type': 'CUSTOM', 'name': 'agent_activity', 'value': {
            'id': 'thinking:unique', 'kind': 'thinking', 'label': '思考', 'status': 'running', 'detail': detail}}
    events = [state('文字' * index) for index in range(1000)]
    log = AgentEventLog()
    await log.append(message.id, events, 0)
    projected = (await log.load_projection_many([message]))[message.id]
    assert projected == events[-1:]
    assert await AgentEvent.filter(message_id=message.id).count() == 1000
    db = __import__('tortoise').connections.get('default')
    with patch.object(db, 'execute_query_dict', wraps=db.execute_query_dict) as query:
        assert (await log.load_projection_many([message]))[message.id] == projected
        assert not any('WITH ranked' in call.args[0] for call in query.await_args_list)
    with patch.object(db, 'execute_query_dict', wraps=db.execute_query_dict) as query:
        assert (await AgentEventLog().load_projection_many([message]))[message.id] == projected
        assert not any('WITH ranked' in call.args[0] for call in query.await_args_list)
    delta = {'type': 'CUSTOM', 'name': 'agent_activity_delta', 'value': {
        'id': 'thinking:unique', 'kind': 'thinking', 'label': '思考', 'status': 'running', 'detail_delta': '🐱新内容', 'detail_offset': 1998}}
    await log.append(message.id, [delta], 1000)
    projected = (await log.load_projection_many([message]))[message.id]
    assert len(projected) == 2
    assert activity_from_events(projected, 2)[0]['detail'] == '文字' * 999 + '🐱新内容'
    assert await log.size(message) == 1001
    assert len(json.dumps(projected)) < len(json.dumps(events)) // 100
