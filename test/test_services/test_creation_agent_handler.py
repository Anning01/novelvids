import json
import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.function import FunctionModel, DeltaToolCall

from auth.deps import AuthContext
from models.creation_agent import AgentMessage, PromptChange
from models.scene import Scene
from models.usage_record import ModelUsageRecord
from services.ai_task_executor import AiTaskExecutor
from services.creation_agent.handler import CreationAgentTaskHandler, chapter_context
from services.creation_agent.sessions import agent_sessions
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


def test_truncated_output_stays_actionable_after_a_failed_automatic_retry():
    from services.creation_agent.handler import public_run_error
    calls = [{'status': 'completed', 'finish_reason': 'length'}, {'status': 'failed'}]
    assert '输出达到上限' in public_run_error('secret provider payload', calls)
    assert '上下文额度' in public_run_error('上下文超过配置上限', calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('with_constraint', [False, True])
async def test_handler_persists_events_history_and_usage_without_exposing_private_text(monkeypatch, with_constraint):
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    constraint = None
    if with_constraint:
        from models.creation_agent import CreationConstraint
        source = await AgentMessage.get(task=task, role='user')
        constraint = await CreationConstraint.create(novel_id=conversation.novel_id, source_message=source,
            fingerprint='handler-rule', content='灯光保持温暖', source_quote='更温暖', scope={'kind': 'project'})
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield 'Internal planning: inspect scene_id and tool parameters.'
            yield {0: DeltaToolCall(name='get_creation_context', json_args='{}', tool_call_id='read')}
        elif calls == 2:
            from pydantic_ai.messages import ToolReturnPart
            context = next(p.content for m in messages for p in m.parts if isinstance(p, ToolReturnPart))
            target = context['targets'][0]
            yield {0: DeltaToolCall(name='update_storyboard_prompt', tool_call_id='write', json_args=json.dumps({'edits': [{
                'scene_id': target['id'],
                'legacy_prompt': '空站台中央洒下温暖的灯光。',
            }]}, ensure_ascii=False))}
        else:
            yield '已调暖当前镜头。'

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value, task.error_message
    if constraint:
        from services.creation_agent.memory import creation_memory
        from schemas.creation_agent import PromptStatusRequest
        change = await PromptChange.get(task=task)
        assert change.changes[0]['constraint_ids'] == [constraint.id]
        status = await creation_memory.prompt_status(conversation.novel_id,
            PromptStatusRequest(chapter_id=request.chapter_id, targets=request.targets))
        assert status[0]['pending_constraints'] == []
    assert request.message not in str(task.response_data)
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert assistant.content == '已调暖当前镜头。'
    assert 'Internal planning' not in str(assistant.events)
    assert assistant.native_messages
    assert assistant.events[-1]['type'] == 'RUN_FINISHED'
    assert len(assistant.usage['calls']) == 3
    assert assistant.billing_record_id is not None
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1
    assert await PromptChange.filter(task=task).count() == 1
    scene = await Scene.get(id=request.targets[0].id)
    assert '温暖的灯光' in scene.prompt


@pytest.mark.asyncio
async def test_model_error_is_redacted_and_recorded_as_missing_usage(monkeypatch):
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    async def model(messages, info):
        raise RuntimeError('secret-provider-payload')
        yield ''
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert assistant.usage['missing_usage'] is True
    assert 'secret-provider-payload' not in str(assistant.events)
    assert 'secret-provider-payload' not in task.error_message


@pytest.mark.asyncio
async def test_truncated_reasoning_reports_output_limit_and_retains_usage(monkeypatch):
    import httpx
    from openai import AsyncOpenAI

    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())

    def transport(outgoing):
        payload = json.loads(outgoing.content)
        envelope = {'id': 'truncated', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'test-model'}
        chunks = [
            {**envelope, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'reasoning_content': 'synthetic-reasoning'}, 'finish_reason': None}]},
            {**envelope, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'length'}]},
            {**envelope, 'choices': [], 'usage': {'prompt_tokens': 100, 'completion_tokens': payload['max_tokens'], 'total_tokens': 100 + payload['max_tokens']}},
        ]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=''.join(
            'data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n')

    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert task.status == TaskStatusEnum.failed.value
    assert '输出达到上限' in task.error_message
    assert 'synthetic-reasoning' not in task.error_message
    assert assistant.usage['calls'][-1]['finish_reason'] == 'length'
    assert assistant.usage['missing_usage'] is False
    assert await PromptChange.filter(task=task).count() == 0


@pytest.mark.asyncio
async def test_repeated_finalization_does_not_duplicate_billing(monkeypatch):
    from services.billing.recorder import record_ai_task_usage
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    async def model(messages, info):
        yield '请说明希望调整的画面。'
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    await record_ai_task_usage(task, task.response_data)
    await record_ai_task_usage(task, task.response_data)
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1


@pytest.mark.asyncio
async def test_stop_during_model_request_preserves_cancelled_state_and_prevents_write(monkeypatch):
    from controllers.creation_agent import creation_agent_controller
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    started, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def model(messages, info):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        yield {0: DeltaToolCall(name='update_storyboard_prompt', tool_call_id='late-write', json_args=json.dumps({'edits': [{
            'scene_id': request.targets[0].id, 'expected_version': 'not-needed-after-cancel', 'legacy_prompt': '不应保存',
        }]}))}
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    running = asyncio.create_task(executor.run(task))
    await asyncio.wait_for(started.wait(), 2)
    await creation_agent_controller.stop(task.id, AuthContext())
    release.set()
    await asyncio.wait_for(running, 2)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.cancelled.value
    assert calls == 1
    assert await PromptChange.filter(task=task).count() == 0
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert len(assistant.usage['calls']) == 1


@pytest.mark.asyncio
async def test_boot_recovery_records_known_usage_without_replaying_model():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    task.status = TaskStatusEnum.running.value
    await task.save()
    await AgentMessage.filter(task=task, role='assistant').update(usage={
        'calls': [{'index': 1, 'status': 'completed', 'usage_reported': True}],
        'requests': 1, 'input_tokens': 100, 'output_tokens': 20, 'missing_usage': False,
    })
    executor = AiTaskExecutor()
    await executor.fail_stale_on_boot()
    await executor.fail_stale_on_boot()
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('reasoning', [False, True])
async def test_openai_compatible_wire_requests_and_reported_usage(monkeypatch, reasoning):
    import httpx
    from openai import AsyncOpenAI

    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    scene = await Scene.get(id=request.targets[0].id)
    requests = []

    def transport(outgoing):
        payload = json.loads(outgoing.content)
        requests.append(payload)
        assert payload['model'] == 'test-model'
        assert payload['stream'] is True
        assert {tool['function']['name'] for tool in payload['tools']} == {
            'get_creation_context', 'update_image_prompt', 'update_storyboard_prompt', 'final_result'}
        assert 'expected_version' not in json.dumps(payload['tools'])
        if len(requests) == 1:
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'wire-read', 'type': 'function', 'function': {
                'name': 'get_creation_context', 'arguments': '{}'}}]}
            finish = 'tool_calls'
        elif len(requests) == 2:
            assert any(message['role'] == 'tool' and 'targets' in message['content'] for message in payload['messages'])
            delta = {'role': 'assistant', 'content': '正在处理内部 scene_id。', 'tool_calls': [{'index': 0, 'id': 'wire-write', 'type': 'function', 'function': {
                'name': 'update_storyboard_prompt', 'arguments': json.dumps({'edits': [{
                    'scene_id': scene.id, 'legacy_prompt': '空站台笼罩在暖色灯光下。',
                }]}, ensure_ascii=False)}}]}
            finish = 'tool_calls'
        else:
            assert any(message['role'] == 'tool' and 'saved' in message['content'] for message in payload['messages'])
            if reasoning:
                previous = next(message for message in payload['messages'] if message.get('tool_calls'))
                assert previous['reasoning_content'] == 'synthetic-reasoning'
            delta, finish = {'role': 'assistant', 'content': '已调暖灯光。'}, 'stop'
        base = {'id': f'completion-{len(requests)}', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'test-model'}
        usage = {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120}
        if reasoning:
            usage['completion_tokens_details'] = {'reasoning_tokens': 7}
        chunks = [
            {**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
            {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}]},
            {**base, 'choices': [], 'usage': usage},
        ]
        if reasoning:
            chunks.insert(0, {**base, 'choices': [{'index': 0,
                'delta': {'role': 'assistant', 'reasoning_content': 'synthetic-reasoning'}, 'finish_reason': None}]})
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            text=''.join('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n')

    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db(); await scene.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value, task.error_message
    assert len(requests) == 3 and '暖色灯光' in scene.prompt
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert assistant.usage['input_tokens'] == 300
    assert assistant.usage['output_tokens'] == 60
    assert assistant.usage['missing_usage'] is False
    assert assistant.content == '已调暖灯光。'
    assert 'synthetic-reasoning' not in assistant.content
    assert not any(event['type'].startswith('THINKING') for event in assistant.events)
    if reasoning:
        assert all(call['usage']['details']['reasoning_tokens'] == 7 for call in assistant.usage['calls'])


@pytest.mark.asyncio
async def test_failed_billing_claim_can_retry_without_losing_or_duplicating_usage(monkeypatch):
    from services.billing.recorder import record_ai_task_usage, billing_recorder
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    task.status = TaskStatusEnum.completed.value
    task.started_at = task.created_at
    task.finished_at = task.updated_at
    task.response_data = {}
    await task.save()
    await AgentMessage.filter(task=task, role='assistant').update(usage={
        'calls': [{'status': 'completed', 'usage_reported': True}], 'requests': 1,
        'input_tokens': 100, 'output_tokens': 20, 'missing_usage': False,
    })
    original = billing_recorder.record_text
    monkeypatch.setattr(billing_recorder, 'record_text', AsyncMock(return_value=None))
    await record_ai_task_usage(task, {})
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert assistant.billing_record_id is None
    monkeypatch.setattr(billing_recorder, 'record_text', original)
    await record_ai_task_usage(task, {})
    await record_ai_task_usage(task, {})
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1


@pytest.mark.asyncio
async def test_chapter_context_is_bounded_and_reports_truncation():
    from models.chapter import Chapter
    from models.novel import Novel
    novel = await Novel.create(name='上下文预算')
    chapter = await Chapter.create(novel=novel, number=2, name='长章节', content='甲' * 1000 + '乙' * 1000)
    context = chapter_context(chapter, 400)
    assert context['content_truncated'] is True
    assert context['content_characters'] == 2000
    assert context['content_excerpt'].startswith('甲' * 100)
    assert context['content_excerpt'].endswith('乙' * 100)
    assert len(context['content_excerpt']) < 500


@pytest.mark.asyncio
async def test_agent_can_read_bounded_middle_of_current_chapter_and_correct_invalid_offset(monkeypatch):
    from models.chapter import Chapter
    from pydantic_ai.messages import ToolReturnPart, RetryPromptPart

    conversation, request, _ = await session_fixture()
    await Chapter.filter(id=request.chapter_id).update(content='甲' * 15000 + '她的左手受伤，仍穿灰色风衣。' + '乙' * 15000)
    task = await agent_sessions.submit(conversation, request, AuthContext())
    task.request_params['agent_configuration']['max_context_characters'] = 28000
    await task.save(update_fields=['request_params'])
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {0: DeltaToolCall(name='get_creation_context', json_args='{"chapter_offset": 999999}', tool_call_id='invalid-offset')}
        elif calls == 2:
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
            yield {0: DeltaToolCall(name='get_creation_context', json_args='{"chapter_offset": 15000}', tool_call_id='read-middle')}
        else:
            result = next(part.content for message in messages for part in message.parts if isinstance(part, ToolReturnPart))
            excerpt = result['context']['chapter']
            assert excerpt['id'] == request.chapter_id
            assert excerpt['content_offset'] == 15000
            assert excerpt['content_excerpt'].startswith('她的左手受伤，仍穿灰色风衣。')
            assert len(excerpt['content_excerpt']) <= 28000 // 3
            assert excerpt['content_next_offset'] == 15000 + 28000 // 3
            yield '当前章节中段写明她的左手受伤，仍穿灰色风衣。'

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value, task.error_message
    assert calls == 3
    assert not await PromptChange.filter(task=task).exists()


def test_chapter_excerpt_does_not_accept_reading_without_a_selected_chapter():
    with pytest.raises(ValueError, match='未选择章节'):
        chapter_context(None, 500, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled_field', ['is_active', 'supports_tool_calls'])
async def test_disabling_model_during_request_prevents_the_returned_tool_from_writing(monkeypatch, disabled_field):
    from models.config import AiModelConfig
    from services.creation_agent.tools import prompt_version
    conversation, request, config = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    scene = await Scene.get(id=request.targets[0].id)
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        await AiModelConfig.filter(id=config.id).update(**{disabled_field: False})
        yield {0: DeltaToolCall(name='update_storyboard_prompt', tool_call_id='disabled-write', json_args=json.dumps({'edits': [{
            'scene_id': scene.id, 'expected_version': prompt_version(scene), 'legacy_prompt': '模型停用后不应保存的暖光。',
        }]}, ensure_ascii=False))}

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert calls == 1
    assert not await PromptChange.filter(task=task).exists()
    assert (await Scene.get(id=scene.id)).prompt == '空站台'
    assert (await AgentMessage.get(task=task, role='assistant')).usage['requests'] == 1
