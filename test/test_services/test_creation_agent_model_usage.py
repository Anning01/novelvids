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
async def test_configured_model_preserves_reasoning_usage_totals(monkeypatch, tmp_path, streaming, with_usage):
    raw_usage = {'prompt_tokens': 2805, 'completion_tokens': 60, 'total_tokens': 2865,
                 'prompt_tokens_details': {'cached_tokens': 200},
                 'completion_tokens_details': {'reasoning_tokens': 47}}

    async def respond(request):
        body = json.loads(request.content)
        assert body['stream'] is streaming
        assert body['max_tokens'] == 100
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
    model = handler.configured_model(SimpleNamespace(base_url='https://example.invalid', api_key='synthetic',
                                                    model='reasoning-model', thinking='disabled'), AgentConfiguration())
    ledger = EvaluationSpendLedger(tmp_path / 'spend.jsonl', {
        'type': 'text', 'currency': 'CNY', 'input_price_per_1m': 9, 'output_price_per_1m': 27})
    guarded = BudgetedEvaluationModel(model, ledger)
    try:
        messages = [ModelRequest(parts=[UserPromptPart('读取当前镜头')])]
        if streaming:
            async with guarded.request_stream(messages, {'max_tokens': 100}, ModelRequestParameters()) as response:
                async for _ in response:
                    pass
                usage = response.usage()
        else:
            usage = (await guarded.request(messages, {'max_tokens': 100}, ModelRequestParameters())).usage
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
