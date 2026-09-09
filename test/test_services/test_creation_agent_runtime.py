import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart, RetryPromptPart
from pydantic_ai.models.function import FunctionModel, DeltaToolCall
from pydantic_ai.usage import UsageLimits

from models.creation_agent import PromptChange
from services.creation_agent.runtime import CreationAgentDeps, creation_agent, stream_creation_agent
from test.test_services.test_creation_agent_tools import setup_service


@pytest.mark.asyncio
async def test_framework_tool_loop_saves_before_reporting_completion():
    service, _, asset, _, _ = await setup_service()
    calls = []

    def model(messages, info):
        calls.append(messages)
        assert {t.name for t in info.function_tools} == {'get_creation_context', 'update_image_prompt', 'update_storyboard_prompt'}
        if len(calls) == 1:
            image_tool = next(t for t in info.function_tools if t.name == 'update_image_prompt')
            assert 'expected_version' not in json.dumps(image_tool.parameters_json_schema)
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='read')])
        if len(calls) == 2:
            return ModelResponse(parts=[ToolCallPart('update_image_prompt', {'edits': [{
                'target_kind': 'asset', 'target_id': asset.id,
                'prompt': '灰色风衣，柔和逆光',
            }]}, tool_call_id='call-1')])
        results = [p for m in messages for p in m.parts if isinstance(p, ToolReturnPart)]
        assert results[-1].content['status'] == 'saved'
        return ModelResponse(parts=[TextPart('已调整光线。')])

    result = await creation_agent.run('让光线柔和一些', model=FunctionModel(model),
        deps=CreationAgentDeps(service=service, context={}), usage_limits=UsageLimits(request_limit=4))
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣，柔和逆光'
    assert len(calls) == 3
    assert result.output == '已调整光线。'
    returned = next(part.content for message in result.new_messages() for part in message.parts
                    if isinstance(part, ToolReturnPart) and part.tool_name == 'update_image_prompt')
    assert returned['status'] == 'saved'
    assert returned['changes'][0]['target_id'] == asset.id
    assert 'before' not in returned['changes'][0] and 'after' not in returned['changes'][0]


@pytest.mark.asyncio
async def test_official_ag_ui_stream_contains_real_tool_result_and_text():
    service, _, asset, _, task = await setup_service()
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {0: DeltaToolCall(name='get_creation_context', tool_call_id='read', json_args='{}')}
        elif calls == 2:
            yield {0: DeltaToolCall(name='update_image_prompt', tool_call_id='stream-call', json_args=json.dumps({'edits': [{
                'target_kind': 'asset', 'target_id': asset.id,
                'prompt': '灰色风衣，阴天柔光',
            }]}, ensure_ascii=False))}
        else:
            yield '已保存。'

    events = [event async for event in stream_creation_agent(
        message='让光线柔和一些', conversation_id='test-thread', run_id=str(task.id),
        model=FunctionModel(stream_function=model), deps=CreationAgentDeps(service=service, context={}),
        usage_limits=UsageLimits(request_limit=4),
    )]
    kinds = [event.type for event in events]
    assert 'TOOL_CALL_START' in kinds and 'TOOL_CALL_RESULT' in kinds
    assert kinds[-1] == 'RUN_FINISHED'
    assert any(getattr(event, 'delta', None) == '已保存。' for event in events)
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣，阴天柔光'


@pytest.mark.asyncio
async def test_agent_reads_context_and_corrects_a_rejected_storyboard_edit():
    service, scene, _, _, _ = await setup_service()
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='read')])
        if calls == 2:
            result = next(p for m in messages for p in m.parts if isinstance(p, ToolReturnPart))
            current = next(t for t in result.content['targets'] if t['kind'] == 'scene')
            assert current['id'] == scene.id and 'version' not in current
            text = '镜头1的女生走向门口。'
        elif calls == 3:
            assert any(isinstance(p, RetryPromptPart) for m in messages for p in m.parts)
            text = '空站台中央的门缓缓打开，暖光照亮地面。'
        else:
            return ModelResponse(parts=[TextPart('已修改当前镜头。')])
        return ModelResponse(parts=[ToolCallPart('update_storyboard_prompt', {'edits': [{
            'scene_id': scene.id, 'legacy_prompt': text,
        }]}, tool_call_id=f'edit-{calls}')])

    await creation_agent.run('让这个镜头更温暖', model=FunctionModel(model),
        deps=CreationAgentDeps(service=service, context={}), usage_limits=UsageLimits(request_limit=4))
    await scene.refresh_from_db()
    assert '暖光照亮地面' in scene.prompt
    assert calls == 4


@pytest.mark.asyncio
async def test_server_owned_version_detects_concurrent_edit_and_refreshes_before_retry():
    service, _, asset, _, _ = await setup_service()
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='read-old')])
        if calls == 2:
            await type(asset).filter(id=asset.id).update(base_traits='用户刚改成黑色风衣')
            return ModelResponse(parts=[ToolCallPart('update_image_prompt', {'edits': [{
                'target_kind': 'asset', 'target_id': asset.id,
                # Even a model-supplied token cannot bypass the server snapshot.
                'expected_version': 'forged', 'prompt': '用户刚改成黑色风衣，柔和逆光',
            }]}, tool_call_id='stale-write')])
        if calls == 3:
            assert any(isinstance(p, RetryPromptPart) for m in messages for p in m.parts)
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='read-new')])
        if calls == 4:
            return ModelResponse(parts=[ToolCallPart('update_image_prompt', {'edits': [{
                'target_kind': 'asset', 'target_id': asset.id,
                'prompt': '用户刚改成黑色风衣，柔和逆光',
            }]}, tool_call_id='fresh-write')])
        return ModelResponse(parts=[TextPart('已按最新版本保存。')])

    result = await creation_agent.run('加入柔和逆光', model=FunctionModel(model),
        deps=CreationAgentDeps(service=service, context={}), usage_limits=UsageLimits(request_limit=6))
    await asset.refresh_from_db()
    assert calls == 5
    assert asset.base_traits == '用户刚改成黑色风衣，柔和逆光'
    assert result.output == '已按最新版本保存。'


@pytest.mark.asyncio
async def test_final_reply_retries_internal_ids_without_repeating_the_write():
    service, _, asset, _, _ = await setup_service()
    calls = 0

    def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ModelResponse(parts=[ToolCallPart('get_creation_context', {}, tool_call_id='read')])
        if calls == 2:
            return ModelResponse(parts=[ToolCallPart('update_image_prompt', {'edits': [{
                'target_kind': 'asset',
                'target_id': asset.id,
                'prompt': '灰色风衣，柔和逆光',
            }]}, tool_call_id='write')])
        if calls == 3:
            return ModelResponse(parts=[TextPart(f'已保存 asset {asset.id}。')])
        assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        return ModelResponse(parts=[TextPart('已保存女主的柔和逆光。')])

    result = await creation_agent.run(
        '加入柔和逆光',
        model=FunctionModel(model),
        deps=CreationAgentDeps(service=service, context={}),
        usage_limits=UsageLimits(request_limit=5),
    )
    await asset.refresh_from_db()
    assert calls == 4
    assert asset.base_traits == '灰色风衣，柔和逆光'
    assert result.output == '已保存女主的柔和逆光。'
    assert await PromptChange.filter(tool_call_id='write').count() == 1
