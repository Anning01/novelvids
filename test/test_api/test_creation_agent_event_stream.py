import asyncio

import pytest
from pydantic_ai.models.function import FunctionModel

from api.creation_agent import stream
from auth.deps import AuthContext
from controllers.creation_agent import creation_agent_controller
from models.creation_agent import AgentMessage
from services.ai_task_executor import AiTaskExecutor
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.handler import CreationAgentTaskHandler
from services.creation_agent.sessions import agent_sessions
from test.query_counting import count_queries
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class FollowRequest:
    """订阅端点的最小请求替身，只回答客户端是否断开。"""

    def __init__(self):
        self.disconnected = False

    async def is_disconnected(self) -> bool:
        return self.disconnected


def _run_event(conversation, task, kind: str, **fields) -> dict:
    return {'type': kind, 'threadId': str(conversation.id), 'runId': str(task.id), **fields}


async def _shutdown(consumer: asyncio.Task) -> None:
    """Always release the follower so a failing assertion cannot leak it into later tests."""
    if not consumer.done():
        consumer.cancel()
    try:
        await consumer
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    except Exception:
        pass


async def _follow(task, after: int = 0):
    request = FollowRequest()
    response = await stream(task.id, request, None, after, AuthContext())
    chunks: list[str] = []

    async def consume():
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    return request, asyncio.create_task(consume()), chunks


@pytest.mark.asyncio
async def test_a_followed_active_run_reads_the_database_only_when_notified():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    assistant = await AgentMessage.get(task=task, role='assistant')
    await agent_event_log.append(assistant.id, [_run_event(conversation, task, 'RUN_STARTED')], 0)
    _, consumer, chunks = await _follow(task)
    try:
        await asyncio.sleep(0.1)
        assert chunks and 'RUN_STARTED' in chunks[0]
        async with count_queries() as statements:
            await asyncio.sleep(0.4)
            idle_queries = len(statements)
            await AgentMessage.filter(id=assistant.id).exists()
            assert len(statements) == idle_queries + 1, '采样器在测量窗口内必须有效'
        assert idle_queries == 0, f'运行中空闲等待仍按固定节奏读库 {idle_queries} 次'
    finally:
        await _shutdown(consumer)


@pytest.mark.asyncio
async def test_idle_connection_has_heartbeats_without_fake_events(monkeypatch):
    monkeypatch.setattr('api.creation_agent._STREAM_IDLE_FALLBACK_SECONDS', 0.02)
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    assistant = await AgentMessage.get(task=task, role='assistant')
    await agent_event_log.append(assistant.id, [_run_event(conversation, task, 'RUN_STARTED')], 0)
    _, consumer, chunks = await _follow(task)
    try:
        await asyncio.sleep(0.08)
        assert any(chunk == ': keep-alive\n\n' for chunk in chunks)
        assert len(await agent_event_log.load(assistant)) == 1
        await task.refresh_from_db()
        assert task.status == TaskStatusEnum.pending.value
    finally:
        await _shutdown(consumer)


@pytest.mark.asyncio
async def test_resumed_attempt_does_not_replay_a_previous_terminal_error():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    assistant = await AgentMessage.get(task=task, role='assistant')
    await agent_event_log.append(assistant.id, [
        _run_event(conversation, task, 'RUN_STARTED'),
        {'type': 'RUN_ERROR', 'message': '上一轮错误'},
        _run_event(conversation, task, 'RUN_STARTED'),
        _run_event(conversation, task, 'RUN_FINISHED'),
    ], 0)
    await AgentMessage.filter(id=assistant.id).update(run_input={'stream_start_seq': 2})
    task.status = 3
    await task.save(update_fields=['status'])
    _, consumer, chunks = await _follow(task)
    await asyncio.wait_for(consumer, 2)
    text = ''.join(chunks)
    assert text.count('RUN_STARTED') == 1 and 'RUN_ERROR' not in text


@pytest.mark.asyncio
async def test_following_stream_closes_from_published_events_when_the_run_finishes(monkeypatch):
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())

    async def model(messages, info):
        yield '本次无需改动。'

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    _, consumer, chunks = await _follow(task)
    try:
        await asyncio.wait_for(executor.run(task), 10)
        await asyncio.wait_for(consumer, 10)
        text = ''.join(chunks)
        assert 'RUN_STARTED' in text
        assert 'RUN_FINISHED' in text
        assert 'RUN_ERROR' not in text
        await task.refresh_from_db()
        assert task.status == TaskStatusEnum.completed.value
    finally:
        await _shutdown(consumer)


@pytest.mark.asyncio
async def test_reconnect_resumes_replay_from_the_after_cursor():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    task.status = TaskStatusEnum.completed.value
    await task.save()
    assistant = await AgentMessage.get(task=task, role='assistant')
    stored = [_run_event(conversation, task, 'RUN_STARTED'),
              {'type': 'TEXT_MESSAGE_START', 'messageId': 'm', 'role': 'assistant'},
              _run_event(conversation, task, 'RUN_FINISHED')]
    await agent_event_log.append(assistant.id, stored, 0)
    _, consumer, chunks = await _follow(task, after=2)
    try:
        await asyncio.wait_for(consumer, 2)
        text = ''.join(chunks)
        assert 'RUN_FINISHED' in text
        assert 'RUN_STARTED' not in text
        assert 'TEXT_MESSAGE_START' not in text
    finally:
        await _shutdown(consumer)


@pytest.mark.asyncio
async def test_stopping_a_followed_run_publishes_a_cancelled_closing_event():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    assistant = await AgentMessage.get(task=task, role='assistant')
    await agent_event_log.append(assistant.id, [_run_event(conversation, task, 'RUN_STARTED')], 0)
    _, consumer, chunks = await _follow(task)
    try:
        await asyncio.sleep(0.1)
        assert chunks and 'RUN_STARTED' in chunks[0]
        await creation_agent_controller.stop(task.id, AuthContext())
        await asyncio.wait_for(consumer, 2)
        text = ''.join(chunks)
        assert 'CANCELLED' in text
        assert 'RUN_FINISHED' not in text
    finally:
        await _shutdown(consumer)


@pytest.mark.asyncio
async def test_an_interrupted_run_closes_with_the_recorded_error():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    task.status = TaskStatusEnum.failed.value
    task.error_message = 'model connection interrupted'
    await task.save()
    assistant = await AgentMessage.get(task=task, role='assistant')
    await agent_event_log.append(assistant.id, [_run_event(conversation, task, 'RUN_STARTED'),
        {'type': 'TEXT_MESSAGE_START', 'messageId': 'm', 'role': 'assistant'}], 0)
    _, consumer, chunks = await _follow(task)
    try:
        await asyncio.wait_for(consumer, 2)
        text = ''.join(chunks)
        assert 'RUN_STARTED' in text
        assert 'INTERRUPTED' in text
        assert 'model connection interrupted' in text
    finally:
        await _shutdown(consumer)
