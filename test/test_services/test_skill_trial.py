import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic_ai.messages import PartStartEvent, TextPart
from pydantic_ai.usage import RequestUsage

from api.user_skill import router
from auth.deps import AuthContext, get_auth_context
from models.ai_task import AiTask
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from schemas.user_skill import SkillTrialInput, UserSkillInput
from services import skill_trial


def body(config_id, **updates):
    return SkillTrialInput(skill=UserSkillInput(task='story', name='测试',
        instructions='---\nname: test\n---\n# 方法\n保留 {{input}}\n```json\n{}\n```'),
        model_config_id=config_id, input='测试素材', **updates)


async def config(**updates):
    return await AiModelConfig.create(name='试运行', task_type=7, model='test',
        base_url='https://model.invalid', api_key='not-a-real-key', supports_json_output=True, supports_strict_output=True,
        thinking='enabled', reasoning_effort='high', is_active=True, **updates)


@pytest.mark.asyncio
async def test_trial_uses_draft_production_schema_and_request_only_overrides():
    chosen = await config()
    request = body(chosen.id, thinking='disabled', reasoning_effort='')
    snapshot, instructions, content, contract = await skill_trial.prepare_trial(request, AuthContext(is_super_admin=True))
    assert snapshot.thinking == 'disabled' and snapshot.reasoning_effort is None
    await chosen.refresh_from_db()
    assert chosen.thinking == 'enabled' and chosen.reasoning_effort == 'high'
    assert json.loads(content)['creative_method']['instructions'] == request.skill.instructions.replace('{{input}}', '测试素材')
    assert 'output_schema=' not in instructions and 'story_outline' in contract['schema']['properties']
    assert json.loads(content)['task_context']['input'] == '测试素材'
    for changes in ({'team_id': 2}, {'supports_strict_output': False}, {'is_active': False}):
        await AiModelConfig.filter(id=chosen.id).update(**changes)
        with pytest.raises(HTTPException) as caught:
            await skill_trial.prepare_trial(request, AuthContext(is_super_admin=True))
        assert caught.value.status_code == 400
        await AiModelConfig.filter(id=chosen.id).update(team_id=None, supports_strict_output=True, is_active=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('task', ['story', 'screenplay', 'assets', 'storyboard'])
async def test_each_category_has_platform_owned_schema(task):
    chosen = await config()
    request = body(chosen.id)
    request.skill.task = task
    _, _, _, contract = await skill_trial.prepare_trial(request, AuthContext(is_super_admin=True))
    assert contract['schema']['additionalProperties'] is False


class FakeStream:
    finish_reason = 'stop'

    def __init__(self, text='{"story_outline":"输出"}', cancel=False):
        self.text = text
        self.cancel = cancel

    async def __aiter__(self):
        yield PartStartEvent(index=0, part=TextPart(self.text))
        if self.cancel:
            raise asyncio.CancelledError()

    def usage(self):
        return RequestUsage(input_tokens=17, output_tokens=9)


class FakeModel:
    def __init__(self, stream):
        self.stream = stream
        self.client = SimpleNamespace(close=AsyncMock())
        self.requests = 0

    @asynccontextmanager
    async def request_stream(self, *args):
        self.requests += 1
        yield self.stream


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'invalid', 'cancelled'])
async def test_trial_stream_single_request_and_accounting_even_on_stop(monkeypatch, mode):
    chosen = await config()
    request = body(chosen.id)
    ctx = AuthContext(is_super_admin=True)
    model = FakeModel(FakeStream('not json' if mode == 'invalid' else '{"story_outline":"输出"}', mode == 'cancelled'))
    monkeypatch.setattr(skill_trial, 'configured_model', lambda *args, **kwargs: model)
    prepared = await skill_trial.prepare_trial(request, ctx)
    received = []
    try:
        async for frame in skill_trial.stream_trial(request, ctx, prepared):
            received.append(json.loads(frame.removeprefix('data: ')))
    except asyncio.CancelledError:
        assert mode == 'cancelled'
    assert model.requests == 1
    model.client.close.assert_awaited_once()
    record = await ModelUsageRecord.get()
    assert record.novel_id == 0 and record.usage['input_tokens'] == 17 and record.usage['output_tokens'] == 9
    task = await AiTask.get(id=record.ai_task_id)
    assert task.status == {'success': 3, 'invalid': 4, 'cancelled': 5}[mode]
    assert 'api_key' not in json.dumps(task.request_params)
    assert any(event['type'] == 'output' and '输出' in event['delta'] for event in received) == (mode != 'invalid')
    assert any(event['type'] == 'done' for event in received) == (mode == 'success')


@pytest.mark.asyncio
async def test_endpoint_rejects_unknown_models_and_schema_injection():
    app = FastAPI()
    app.include_router(router, prefix='/skills')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        payload = body(999).model_dump()
        assert (await client.post('/skills/trial', json=payload)).status_code == 400
        assert (await client.post('/skills/trial', json={**payload, 'output_schema': {}})).status_code == 422
    assert await AiTask.all().count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('text_api', ['chat_completions', 'responses'])
async def test_trial_endpoint_sends_one_strict_request_through_each_configured_protocol(monkeypatch, text_api):
    from test.test_services.test_strict_text_tasks import mock_model
    chosen = await config(text_api=text_api)
    payload = {'book_types': ['悬疑'], 'story_outline': '船工发现秘密。', 'key_characters': []}
    requests = mock_model(monkeypatch, payload)
    app = FastAPI()
    app.include_router(router, prefix='/skills')
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(is_super_admin=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/skills/trial', json=body(chosen.id, thinking='disabled', reasoning_effort='low').model_dump())
    assert response.status_code == 200 and '"type": "done"' in response.text
    assert len(requests) == 1
    assert 'output_schema=' not in json.dumps(requests[0], ensure_ascii=False)
    output_format = requests[0]['text']['format'] if text_api == 'responses' else requests[0]['response_format']['json_schema']
    assert output_format['strict'] is True and output_format['schema']['additionalProperties'] is False
    assert (await ModelUsageRecord.get()).usage['input_tokens'] == 24


@pytest.mark.asyncio
async def test_trial_counts_native_schema_against_configured_context_limit():
    chosen = await config()
    request = body(chosen.id)
    _, instructions, content, _ = await skill_trial.prepare_trial(request, AuthContext(is_super_admin=True))
    await AiModelConfig.filter(id=chosen.id).update(max_context_characters=len(instructions) + len(content) + 1)
    with pytest.raises(HTTPException) as caught:
        await skill_trial.prepare_trial(request, AuthContext(is_super_admin=True))
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_trial_pacing_resolves_the_same_placeholders_as_episode_generation():
    chosen = await config()
    request = body(chosen.id, episode_pacing={'preset': 'fast', 'max_seconds': 75})
    request.skill.task = 'screenplay'
    request.skill.instructions = '配置 {{episode_pacing}}；时长 {{max_seconds}}'
    _, _, content, _ = await skill_trial.prepare_trial(request, AuthContext(is_super_admin=True))
    payload = json.loads(content)
    assert payload['creative_method']['instructions'] == '配置 {"preset": "fast", "max_seconds": 75}；时长 75'
    assert payload['task_context']['episode_pacing'] == {'preset': 'fast', 'max_seconds': 75}
    assert request.skill.instructions == '配置 {{episode_pacing}}；时长 {{max_seconds}}'
