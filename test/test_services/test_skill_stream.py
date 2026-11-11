import asyncio
import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import RetryPromptPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from auth.deps import AuthContext
from controllers.creation_agent import creation_agent_controller
from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from prompts.skill_pack import ROOT, SkillSnapshot, instructions, snapshot_skills
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.production import conversation_for_task
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.skill_execution import SkillExecution, prepare_workflow
from services.creation_agent.skill_stream import SkillRunActivity
from test.test_services.test_creation_agent_sessions import session_fixture


def test_selected_package_is_frozen_without_changing_language_or_required_contracts():
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    entry = (ROOT / 'novelvids-screenplay/SKILL.md').read_text()
    assert snapshot.read('novelvids-screenplay') == entry
    snapshot.contents['novelvids-screenplay'] = 'Frozen package entry'
    assert 'Frozen package entry' in instructions(snapshot, 'en', 'screenplay')
    assert 'language=en' in instructions(snapshot, 'en', 'screenplay')
    assert snapshot.read('screenplay') in instructions(snapshot, 'en', 'screenplay')
    del snapshot.contents['novelvids-screenplay']
    assert snapshot.read('screenplay') in instructions(snapshot, 'zh', 'screenplay')
    with pytest.raises(ValueError):
        snapshot.read('novelvids-story/../../.env')


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_selected_skill_stream_is_visible_in_snapshot_before_completion(cancel):
    conversation, request, _ = await session_fixture()
    parent = await agent_sessions.submit(conversation, request, AuthContext())
    params = await prepare_workflow({'novel_id': conversation.novel_id, 'prompt_language': 'zh'})
    production = await AiTask.create(task_type=5, status=2, request_params=params)
    message = await conversation_for_task(production)
    await AgentOperation.create(task=parent, key='submit:' + str(uuid4()), state='completed',
                                result={'task_id': str(production.id)})
    execution = SkillExecution({**params, 'task_id': str(production.id)}, message, AsyncMock())
    reached = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Output(BaseModel):
        result: str

    async def respond(messages, info):
        nonlocal calls
        calls += 1
        assert 'name: novelvids-screenplay' in info.instructions
        if calls == 1:
            yield {0: DeltaToolCall(name='read_skill', tool_call_id='skill-selection',
                                   json_args=json.dumps({'name': 'novelvids-screenplay'}))}
        else:
            returned = [part for msg in messages for part in msg.parts if isinstance(part, ToolReturnPart)]
            assert 'name: novelvids-screenplay' in returned[-1].content
            reached.set()
            await release.wait()
            yield {0: DeltaToolCall(name=info.output_tools[0].name, tool_call_id='final',
                                   json_args='{"result":"ok"}')}

    model = FunctionModel(stream_function=respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        work = asyncio.create_task(execution.generate('screenplay', {'source': 'synthetic'}, Output))
        try:
            await asyncio.wait_for(reached.wait(), 5)
            assert not work.done()
            snapshot = await creation_agent_controller.snapshot(parent.id, AuthContext())
            tool = next(item for item in snapshot.activity if item.tool_name == 'read_skill')
            assert tool.status == 'completed'
            assert any(item.status == 'running' for item in snapshot.activity)
            assert not any(item.kind == 'thinking' for item in snapshot.activity)
            if cancel:
                work.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await work
            else:
                release.set()
                assert (await work).result == 'ok'
        finally:
            if not work.done():
                work.cancel()
            await asyncio.gather(work, return_exceptions=True)
    snapshot = await creation_agent_controller.snapshot(parent.id, AuthContext())
    assert not any(item.status == 'running' for item in snapshot.activity)
    children = await AgentMessage.filter(conversation_id=message.conversation_id).exclude(id=message.id)
    events = [event for child in children for event in await agent_event_log.load(child)]
    tool_events = [event['value'] for event in events if event['value']['kind'] == 'tool']
    assert [item['status'] for item in tool_events] == ['running', 'completed']
    assert 'SKILL.md' not in str(tool_events) and 'json_args' not in str(tool_events)


@pytest.mark.asyncio
@pytest.mark.parametrize('terminal', ['retry', 'exception', 'cancel'])
async def test_sdk_tool_activity_closes_rejected_or_interrupted_tools(terminal):
    sink = SkillRunActivity(AsyncMock(task_id='child', conversation_id=1), 'owner')
    sink.publish = AsyncMock()

    async def events():
        yield FunctionToolCallEvent(ToolCallPart('read_skill', {'private': 'data'}, tool_call_id='read'))
        if terminal == 'retry':
            yield FunctionToolResultEvent(RetryPromptPart('private failure', tool_name='read_skill', tool_call_id='read'))
        elif terminal == 'exception':
            raise RuntimeError('private failure')
        else:
            raise asyncio.CancelledError()

    if terminal == 'retry':
        await sink(None, events())
    else:
        with pytest.raises(RuntimeError if terminal == 'exception' else asyncio.CancelledError):
            await sink(None, events())
    items = [call.args[0] for call in sink.publish.await_args_list]
    assert [item['status'] for item in items] == ['running', 'failed']
    assert items[-1]['finished_at'] and not sink.pending
    assert 'private' not in str(items)


@pytest.mark.asyncio
async def test_only_sdk_public_thinking_content_becomes_summary():
    from pydantic_ai import Agent
    from pydantic_ai.models.function import DeltaThinkingPart

    async def respond(messages, info):
        yield {0: DeltaThinkingPart(signature='private-signature')}
        yield {0: DeltaThinkingPart(content='Public model summary.')}
        yield 'Ordinary output is not a thinking summary.'

    sink = SkillRunActivity(AsyncMock(task_id='child', conversation_id=1), 'owner')
    sink.publish_event = AsyncMock()
    result = await Agent().run('synthetic', model=FunctionModel(stream_function=respond),
                               event_stream_handler=sink)
    assert result.output == 'Ordinary output is not a thinking summary.'
    events = [call.args[0] for call in sink.publish_event.await_args_list]
    assert [event['type'] for event in events] == [
        'THINKING_TEXT_MESSAGE_START', 'THINKING_TEXT_MESSAGE_CONTENT', 'THINKING_TEXT_MESSAGE_END']
    assert events[1]['delta'] == 'Public model summary.'
    assert 'private-signature' not in str(events) and 'Ordinary output' not in str(events)
