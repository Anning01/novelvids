import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from schemas.creation_agent import AgentConfiguration
from schemas.config import AiModelConfigPatch
from services.creation_agent.handler import configured_model


@pytest.mark.asyncio
@pytest.mark.parametrize('thinking,effort,expected', [
    (None, None, {}),
    ('enabled', 'low', {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'low'}),
    ('disabled', None, {'thinking': {'type': 'disabled'}}),
    ('low', 'max', {'thinking': 'low', 'reasoning_effort': 'max'}),
    ('adaptive', 'provider-specific', {'thinking': 'adaptive', 'reasoning_effort': 'provider-specific'}),
])
async def test_model_sends_only_explicit_reasoning_parameters(monkeypatch, thinking, effort, expected):
    config = AiModelConfigPatch(thinking=thinking, reasoning_effort=effort)
    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'test',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
    monkeypatch.setattr('services.creation_agent.handler.AsyncOpenAI', lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    model = configured_model(SimpleNamespace(base_url='https://model.invalid/v1', api_key='fixture', api_protocol='openai_compatible',
        model='test', thinking=config.thinking, reasoning_effort=config.reasoning_effort), AgentConfiguration())
    try:
        await model.request([ModelRequest(parts=[UserPromptPart('Hello')])], {'max_tokens': 512}, ModelRequestParameters())
    finally:
        await model.client.close()
    assert len(seen) == 1
    assert {k: seen[0][k] for k in ('thinking', 'reasoning_effort') if k in seen[0]} == expected
    assert 'extra_body' not in seen[0]
