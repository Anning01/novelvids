from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from auth.deps import AuthContext
from controllers.creation_agent import creation_agent_controller
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.creation_agent import AgentMessage
from services.creation_agent.activity import activity_from_events
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.production import conversation_for_task
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.skill_execution import SkillExecution, prepare_workflow
from test.test_services.test_creation_agent_sessions import session_fixture


def test_activity_projects_thinking_and_real_tool_completion_without_arguments():
    events = [
        {'type': 'THINKING_START', 'timestamp': 1000},
        {'type': 'THINKING_TEXT_MESSAGE_START', 'timestamp': 1000},
        {'type': 'THINKING_TEXT_MESSAGE_CONTENT', 'delta': '先核对人物'},
        {'type': 'THINKING_TEXT_MESSAGE_CONTENT', 'delta': '再提取资产'},
        {'type': 'THINKING_TEXT_MESSAGE_END', 'timestamp': 2000},
        {'type': 'THINKING_END', 'timestamp': 2000},
        {'type': 'TOOL_CALL_START', 'toolCallId': 'read', 'toolCallName': 'read_creation_objects', 'timestamp': 2000},
        {'type': 'TOOL_CALL_ARGS', 'toolCallId': 'read', 'delta': 'private-arguments'},
        {'type': 'TOOL_CALL_END', 'toolCallId': 'read', 'timestamp': 2100},
    ]
    result = activity_from_events(events, 2)
    assert result[0]['id'] == 'thinking:1'
    assert result[0]['detail'] == '先核对人物再提取资产'
    assert result[0]['status'] == 'completed'
    assert result[0]['finished_at'] == '1970-01-01T00:00:02+00:00'
    assert result[1]['status'] == 'running'  # end-of-arguments is not tool completion
    assert 'private-arguments' not in str(result)
    events.append({'type': 'TOOL_CALL_RESULT', 'toolCallId': 'read', 'content': 'private-result', 'timestamp': 3000})
    assert activity_from_events(events, 2)[1]['status'] == 'completed'
    assert 'private-result' not in str(activity_from_events(events, 2))
    assert activity_from_events(events[:-1], 4)[1]['status'] == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', [False, True])
async def test_snapshot_and_history_include_child_model_steps_and_timing(failed):
    conversation, request, _ = await session_fixture()
    parent = await agent_sessions.submit(conversation, request, AuthContext())
    now = datetime.now(timezone.utc)
    parent.started_at = now
    await parent.save(update_fields=['started_at'])
    params = await prepare_workflow({'novel_id': conversation.novel_id, 'prompt_language': 'zh'})
    production = await AiTask.create(task_type=5, status=2, request_params=params, started_at=now)
    message = await conversation_for_task(production)
    await AgentOperation.create(task=parent, key='submit:' + str(uuid4()), state='completed', result={'task_id': str(production.id)})
    execution = SkillExecution({**params, 'task_id': str(production.id)}, message, AsyncMock())

    class Output(BaseModel):
        result: str

    def respond(messages, info):
        if failed:
            raise RuntimeError('synthetic provider failure')
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'result': 'ok'})])

    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        if failed:
            with pytest.raises(RuntimeError, match='synthetic provider failure'):
                await execution.generate('story', {'source': 'synthetic'}, Output)
        else:
            assert (await execution.generate('story', {'source': 'synthetic'}, Output)).result == 'ok'
    children = await AgentMessage.filter(conversation=message.conversation_id, role='assistant').exclude(id=message.id)
    assert len(children) == 1
    events = await agent_event_log.load(children[0])
    assert [event['value']['status'] for event in events] == ['running', 'failed' if failed else 'completed']
    assert all(event['name'] == 'agent_activity' for event in events)
    assert events[-1]['value']['finished_at']
    snapshot = await creation_agent_controller.snapshot(parent.id, AuthContext())
    assert snapshot.started_at == now
    assert snapshot.activity[0].label == '分析故事'
    assert snapshot.activity[0].id.startswith('model:')
    assert snapshot.activity[0].status == ('failed' if failed else 'completed')
    assert datetime.fromisoformat(snapshot.production[0]['started_at']) == now
    history = await creation_agent_controller.messages(conversation.id, AuthContext(), None)
    assistant = next(row for row in history['items'] if row['role'] == 'assistant')
    assert assistant['activity'][0]['id'] == snapshot.activity[0].id
    assert assistant['started_at'] == now


def test_elapsed_time_includes_running_and_finished_production():
    from types import SimpleNamespace
    from services.creation_agent.activity import run_timing
    started = datetime(2026, 11, 7, 1, tzinfo=timezone.utc)
    root_end = datetime(2026, 11, 7, 1, 1, tzinfo=timezone.utc)
    child_end = datetime(2026, 11, 7, 1, 3, tzinfo=timezone.utc)
    task = SimpleNamespace(status=3, started_at=started, created_at=started, finished_at=root_end)
    assert run_timing(task, [{'status': 2, 'finished_at': None}])['finished_at'] is None
    assert run_timing(task, [{'status': 3, 'finished_at': child_end.isoformat()}]) == {
        'started_at': started, 'finished_at': child_end,
    }
