from unittest.mock import AsyncMock

import pytest

from auth.deps import AuthContext
from models.creation_agent import AgentMessage, PromptChange
from models.scene import Scene
from services.ai_task_executor import AiTaskExecutor
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.handler import CreationAgentTaskHandler
from services.creation_agent.scene_prompt_run import is_scene_prompt_run
from services.creation_agent.sessions import agent_sessions
from test.test_services.test_creation_agent_sessions import session_fixture
from test.test_services.test_strict_text_tasks import mock_model
from utils.enums import AiTaskTypeEnum


async def setup(monkeypatch, runtime, text_api, *, batch=False):
    conversation, request, config = await session_fixture(runtime)
    config.supports_strict_output = True
    config.text_api = text_api
    await config.save()
    if batch:
        scene = await Scene.create(chapter_id=request.chapter_id, sequence=2, prompt='冷色调，冷色调。', duration=6)
        request.targets.append(request.targets[0].model_copy(update={'id': scene.id}))
    forbidden = AsyncMock(side_effect=AssertionError('selected edits must bypass the chat tool loop'))
    monkeypatch.setattr('services.creation_agent.handler.stream_creation_agent', forbidden)
    monkeypatch.setattr('services.creation_agent.deep_execution.stream_deep_agent', forbidden)
    task = await agent_sessions.submit(conversation, request, AuthContext())
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    return conversation, request, task, executor


@pytest.mark.asyncio
@pytest.mark.parametrize('runtime', ['deepagents', 'pydantic_ai'])
@pytest.mark.parametrize('text_api', ['responses', 'chat_completions'])
async def test_selected_entry_calls_once_saves_once_and_streams(monkeypatch, runtime, text_api):
    conversation, request, task, executor = await setup(monkeypatch, runtime, text_api, batch=True)
    payload = {'prompts': {str(target.id): '暖色调，暖色调。' for target in request.targets}, 'reply': '已调整为暖色调。'}
    calls = mock_model(monkeypatch, payload)
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(calls) == 1 and not calls[0].get('tools')
    changes = await PromptChange.filter(task=task)
    assert len(changes) == 1 and len(changes[0].changes) == 2
    for target in request.targets:
        assert (await Scene.get(id=target.id)).prompt == '暖色调，暖色调。'
    assistant = await AgentMessage.get(task=task, role='assistant')
    events = await agent_event_log.load(assistant)
    assert events[0]['type'] == 'RUN_STARTED' and events[-1]['type'] == 'RUN_FINISHED'
    assert any(event.get('name') == 'agent_activity' for event in events)
    assert not any(event['type'].startswith('TOOL_CALL') for event in events)
    assert 'updated and saved' in assistant.content
    await conversation.refresh_from_db()
    assert conversation.active_task_id is None
    # One provider invocation is recorded on the strict child, not again on the parent.
    children = await AgentMessage.filter(conversation=conversation, role='assistant').exclude(task=task)
    assert sum(len(child.usage.get('calls', [])) for child in children) == 1


@pytest.mark.asyncio
async def test_incomplete_output_stops_without_retry_or_save(monkeypatch):
    _, _, task, executor = await setup(monkeypatch, 'deepagents', 'chat_completions')
    calls = mock_model(monkeypatch, {}, finish_reason='length')
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4 and len(calls) == 1
    assert not await PromptChange.filter(task=task).exists()
    assistant = await AgentMessage.get(task=task, role='assistant')
    events = await agent_event_log.load(assistant)
    assert events[-1]['type'] == 'RUN_ERROR' and events[-1]['message'] == task.error_message


@pytest.mark.asyncio
async def test_question_can_return_without_writing(monkeypatch):
    _, request, task, executor = await setup(monkeypatch, 'deepagents', 'responses')
    calls = mock_model(monkeypatch, {'prompts': {str(request.targets[0].id): None}, 'reply': '当前是冷色调。'})
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3 and len(calls) == 1
    assert not await PromptChange.filter(task=task).exists()
    assert (await AgentMessage.get(task=task, role='assistant')).content == '当前是冷色调。'


@pytest.mark.asyncio
async def test_conflict_in_second_scene_leaves_entire_batch_unsaved(monkeypatch):
    from services.creation_agent.changes import CreationChanges
    _, request, task, executor = await setup(monkeypatch, 'deepagents', 'responses', batch=True)
    original = CreationChanges.save_scene_prompts

    async def concurrent_save(service, prompts, tool_call_id):
        await Scene.filter(id=request.targets[1].id).update(prompt='用户最新修改')
        return await original(service, prompts, tool_call_id)

    monkeypatch.setattr(CreationChanges, 'save_scene_prompts', concurrent_save)
    calls = mock_model(monkeypatch, {'prompts': {str(target.id): '暖色调' for target in request.targets}, 'reply': '暖色调'})
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4 and len(calls) == 1
    assert not await PromptChange.filter(task=task).exists()
    assert (await Scene.get(id=request.targets[0].id)).prompt == '空站台'
    assert (await Scene.get(id=request.targets[1].id)).prompt == '用户最新修改'


@pytest.mark.asyncio
async def test_entry_does_not_intercept_readonly_or_other_scopes():
    _, request, _ = await session_fixture()
    assert is_scene_prompt_run(request)
    assert not is_scene_prompt_run(request.model_copy(update={'message': '生成视频'}))
    assert not is_scene_prompt_run(request.model_copy(update={'message': '生成图片'}))
    assert not is_scene_prompt_run(request.model_copy(update={'write_scope': 'read_only'}))
    assert not is_scene_prompt_run(request.model_copy(update={'write_scope': 'chapter'}))
    assert not is_scene_prompt_run(request.model_copy(update={'targets': []}))
    assert not is_scene_prompt_run(request.model_copy(update={'targets': [request.targets[0].model_copy(update={'kind': 'asset'})]}))


@pytest.mark.asyncio
@pytest.mark.parametrize('stop', ['cancel', 'disable_model'])
async def test_stopped_or_disabled_run_cannot_save(monkeypatch, stop):
    from models.ai_task import AiTask
    from models.config import AiModelConfig
    from services.creation_agent.changes import CreationChanges
    _, request, task, executor = await setup(monkeypatch, 'deepagents', 'responses')
    original = CreationChanges.save_scene_prompts

    async def stop_before_save(service, prompts, tool_call_id):
        if stop == 'cancel':
            await AiTask.filter(id=task.id).update(status=5)
        else:
            await AiModelConfig.filter(id=task.request_params['model_config_id']).update(is_active=False)
        return await original(service, prompts, tool_call_id)

    monkeypatch.setattr(CreationChanges, 'save_scene_prompts', stop_before_save)
    calls = mock_model(monkeypatch, {'prompts': {str(request.targets[0].id): '暖色调'}, 'reply': '暖色调'})
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == (5 if stop == 'cancel' else 4)
    assert len(calls) == 1 and not await PromptChange.filter(task=task).exists()
    assert (await Scene.get(id=request.targets[0].id)).prompt == '空站台'
