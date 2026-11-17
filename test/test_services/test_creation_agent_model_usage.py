"""Use the real SDK parser for OpenAI-compatible usage, including reasoning."""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from schemas.creation_agent import AgentConfiguration
from services.creation_agent import handler
from test.creation_agent_evaluation_budget import BudgetedEvaluationModel, EvaluationSpendLedger


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('with_usage', [True, False])
@pytest.mark.parametrize('output_limit', [None, 100])
async def test_configured_model_preserves_reasoning_usage_totals(monkeypatch, tmp_path, streaming, with_usage, output_limit):
    raw_usage = {'prompt_tokens': 2805, 'completion_tokens': 60, 'total_tokens': 2865,
                 'prompt_tokens_details': {'cached_tokens': 200},
                 'completion_tokens_details': {'reasoning_tokens': 47}}

    async def respond(request):
        body = json.loads(request.content)
        assert body['stream'] is streaming
        assert body['max_tokens'] == (128000 if output_limit is None else output_limit)
        assert 'max_completion_tokens' not in body
        assert body['thinking'] == {'type': 'disabled'}
        envelope = {'id': 'synthetic-response', 'created': 1, 'model': 'reasoning-model'}
        if streaming:
            assert body['stream_options']['include_usage']
            chunks = [{**envelope, 'object': 'chat.completion.chunk', 'choices': [
                {'index': 0, 'delta': {'role': 'assistant', 'content': '已读取'}, 'finish_reason': None}]},
                {**envelope, 'object': 'chat.completion.chunk', 'choices': [
                    {'index': 0, 'delta': {}, 'finish_reason': 'stop'}],
                 'usage': raw_usage if with_usage else None}]
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=''.join(
                f'data: {json.dumps(chunk)}\n\n' for chunk in chunks) + 'data: [DONE]\n\n')
        return httpx.Response(200, json={**envelope, 'object': 'chat.completion', 'choices': [
            {'index': 0, 'message': {'role': 'assistant', 'content': '已读取'}, 'finish_reason': 'stop'}],
            'usage': raw_usage if with_usage else None})

    monkeypatch.setattr(handler, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    model = handler.configured_model(SimpleNamespace(api_protocol='openai_compatible', base_url='https://example.invalid', api_key='synthetic',
                                                    model='reasoning-model', thinking='disabled'), AgentConfiguration())
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', {
        'type': 'text', 'currency': 'CNY', 'input_price_per_1m': 9, 'output_price_per_1m': 27})
    guarded = BudgetedEvaluationModel(model, ledger)
    try:
        messages = [ModelRequest(parts=[UserPromptPart('读取当前镜头')])]
        settings = AgentConfiguration().output_model_settings() if output_limit is None else {'max_tokens': output_limit}
        if streaming:
            async with guarded.request_stream(messages, settings, ModelRequestParameters()) as response:
                async for _ in response:
                    pass
                usage = response.usage()
        else:
            usage = (await guarded.request(messages, settings, ModelRequestParameters())).usage
        assert usage.input_tokens == (2805 if with_usage else 0)
        assert usage.output_tokens == (60 if with_usage else 0)
        assert usage.cache_read_tokens == (200 if with_usage else 0)
        if with_usage:
            assert usage.details['reasoning_tokens'] == 47
        entry = json.loads(ledger.path.read_text().splitlines()[-1])
        assert entry['status'] == ('settled' if with_usage else 'unknown')
        if with_usage:
            assert entry['cost_cny'] == '0.026865'  # 2805 input + 60 output, including reasoning.
    finally:
        await model.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('thinking', [None, 'enabled', 'disabled'])
async def test_structured_agent_uses_auto_tool_choice_compatible_with_reasoning_models(monkeypatch, thinking):
    from pydantic_ai.tools import ToolDefinition

    async def respond(request):
        body=json.loads(request.content)
        assert body['max_tokens'] == 128000
        assert body['tool_choice']=='auto'
        assert body['tools'][0]['function']['name']=='final_result'
        return httpx.Response(200,json={'id':'response','created':1,'model':'test','object':'chat.completion',
            'choices':[{'index':0,'message':{'role':'assistant','tool_calls':[{
                'id':'output','type':'function','function':{'name':'final_result','arguments':'{"result":"ok"}'},
            }]},'finish_reason':'tool_calls'}]})

    monkeypatch.setattr(handler,'AsyncOpenAI',lambda **kwargs: AsyncOpenAI(**kwargs,http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    model=handler.configured_model(SimpleNamespace(api_protocol='openai_compatible', base_url='https://example.invalid',api_key='synthetic',model='test',thinking=thinking),AgentConfiguration())
    try:
        await model.request([ModelRequest(parts=[UserPromptPart('Read the chapter')])],None,
            ModelRequestParameters(output_mode='tool',output_tools=[ToolDefinition(name='final_result',kind='output',parameters_json_schema={
                'type':'object','properties':{'result':{'type':'string'}},'required':['result'],
            })],allow_text_output=False))
    finally: await model.client.close()


@pytest.mark.asyncio
async def test_non_storyboard_models_keep_completed_stream_recovery(monkeypatch):
    from test.test_services.test_storyboard_stream_completion import StreamBody
    def respond(request):
        events = [{'id': 'done', 'created': 1, 'model': 'test', 'object': 'chat.completion.chunk',
            'choices': [{'index': 0, 'delta': {'content': '完整回复'}, 'finish_reason': 'stop'}]}]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=StreamBody(events, True))
    monkeypatch.setattr(handler, 'AsyncOpenAI', lambda **kw: AsyncOpenAI(**kw,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    model = handler.configured_model(SimpleNamespace(api_protocol='openai_compatible',
        base_url='https://example.invalid', api_key='test', model='test'), AgentConfiguration())
    try:
        async with model.request_stream([ModelRequest(parts=[UserPromptPart('测试')])], None, ModelRequestParameters()) as stream:
            async for _ in stream:
                pass
            assert stream.get().parts[0].content == '完整回复'
            assert stream.provider_details['stream_transport_interrupted'] is True
    finally:
        await model.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_responses_preserves_usage_and_native_output_contract(monkeypatch, streaming):
    from test.test_services.test_strict_text_tasks import mock_model
    from schemas.text_task_contracts import output_contract
    requests = mock_model(monkeypatch, {'screenplay': '本集剧本'})
    config = SimpleNamespace(api_protocol='openai_compatible', text_api='responses',
        base_url='https://example.invalid/v1', api_key='synthetic', model='test',
        thinking='disabled', reasoning_effort='high', supports_strict_output=True, supports_json_output=True)
    model = handler.configured_model(config, AgentConfiguration(), output_contract=output_contract('screenplay'))
    try:
        messages = [ModelRequest(parts=[UserPromptPart('创作剧本')])]
        if streaming:
            async with model.request_stream(messages, {'max_tokens': 100}, ModelRequestParameters()) as stream:
                async for _ in stream:
                    pass
                usage = stream.usage()
                assert stream.finish_reason == 'stop'
        else:
            result = await model.request(messages, {'max_tokens': 100}, ModelRequestParameters())
            usage = result.usage
            assert result.finish_reason == 'stop'
        assert usage.input_tokens == 24
        assert usage.output_tokens == 12
        assert usage.cache_read_tokens == 4
        assert requests[0]['max_output_tokens'] == 100
        assert requests[0]['reasoning']['effort'] == 'none'
        assert 'thinking' not in requests[0] and 'response_format' not in requests[0]
        assert requests[0]['text']['format']['strict'] is True
    finally:
        await model.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('event_type,index_field', [
    ('response.reasoning_text.delta', 'content_index'),
    ('response.reasoning_summary_text.delta', 'summary_index'),
])
async def test_responses_thinking_reaches_activity_before_response_finishes(monkeypatch, event_type, index_field):
    from unittest.mock import AsyncMock
    from services.creation_agent.skill_stream import SkillRunActivity
    result = {'id': 'resp-thinking', 'object': 'response', 'created_at': 1, 'model': 'test',
        'status': 'in_progress', 'output': [], 'usage': None}
    sink = SkillRunActivity(AsyncMock(task_id='child', conversation_id=1), 'owner')
    sink.publish_event = AsyncMock()
    class LiveBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            events = [
                {'type': 'response.created', 'response': result},
                {'type': 'response.output_item.added', 'output_index': 0,
                 'item': {'id': 'thinking', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'private-signature'}},
                {'type': event_type, 'item_id': 'thinking', 'output_index': 0, index_field: 0, 'delta': '正在拆分'},
                {'type': event_type, 'item_id': 'thinking', 'output_index': 0, index_field: 0, 'delta': '镜头。'},
            ]
            for index, event in enumerate(events):
                yield ('data: ' + json.dumps({**event, 'sequence_number': index}) + '\n\n').encode()
            # The HTTP stream is still open. A buffered implementation fails here.
            sent = [call.args[0] for call in sink.publish_event.await_args_list]
            assert any('正在拆分' in event['value'].get('detail_delta', '') for event in sent)
            yield ('data: ' + json.dumps({'type': 'response.completed', 'sequence_number': 4,
                'response': {**result, 'status': 'completed'}}) + '\n\n').encode()
    def respond(request):
        assert json.loads(request.content)['stream'] is True
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=LiveBody())
    monkeypatch.setattr(handler, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    model = handler.configured_model(SimpleNamespace(api_protocol='openai_compatible', text_api='responses',
        base_url='https://example.invalid/v1', api_key='test', model='test'), AgentConfiguration())
    try:
        async with model.request_stream([ModelRequest(parts=[UserPromptPart('生成分镜')])], {}, ModelRequestParameters()) as stream:
            await sink(None, stream)
            native = stream.get()
        sent = [call.args[0] for call in sink.publish_event.await_args_list]
        text = ''.join(event['value'].get('detail_delta', '') for event in sent)
        assert text == '正在拆分镜头。'
        assert 'private-signature' not in str(sent)
        if index_field == 'content_index':
            part = native.parts[0]
            assert part.content == ''
            assert part.provider_details['raw_content'] == ['正在拆分镜头。']
    finally:
        await model.client.close()
