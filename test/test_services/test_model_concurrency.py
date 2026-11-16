import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from models.config import AiModelConfig
from schemas.creation_agent import AgentConfiguration


async def config(limit):
    return await AiModelConfig.create(name='concurrency-test', task_type=7, model='test',
        api_key='synthetic', base_url='https://example.invalid', concurrency=limit, supports_tool_calls=True)


def test_legacy_agent_concurrency_is_accepted_but_no_longer_exposed():
    assert 'production_concurrency' not in AgentConfiguration(production_concurrency=4).model_dump()


@pytest.mark.asyncio
async def test_model_slots_share_limit_across_callers_and_release_on_cancel():
    from services.model_concurrency import model_slots
    model = await config(2)
    release = asyncio.Event()
    entered = []
    async def call(index):
        async with model_slots.hold(model.id):
            entered.append(index)
            await release.wait()
    workers = [asyncio.create_task(call(i)) for i in range(4)]
    try:
        for _ in range(100):
            if len(entered) == 2:
                break
            await asyncio.sleep(.005)
        assert len(entered) == 2
        workers[entered[0]].cancel()
        await asyncio.gather(workers[entered[0]], return_exceptions=True)
        for _ in range(100):
            if len(entered) == 3:
                break
            await asyncio.sleep(.005)
        assert len(entered) == 3
    finally:
        release.set()
        await asyncio.gather(*workers, return_exceptions=True)


@pytest.mark.asyncio
async def test_llm_200_is_not_capped_at_four_or_twenty():
    from services.model_concurrency import model_slots
    model = await config(200)
    release, all_started = asyncio.Event(), asyncio.Event()
    active = 0
    async def call():
        nonlocal active
        async with model_slots.hold(model.id):
            active += 1
            if active == 200:
                all_started.set()
            await release.wait()
    workers = [asyncio.create_task(call()) for _ in range(200)]
    try:
        await asyncio.wait_for(all_started.wait(), 5)
        assert active == 200
    finally:
        release.set()
        await asyncio.gather(*workers)


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_agent_requests_share_the_configured_llm_capacity(monkeypatch, streaming):
    from contextlib import asynccontextmanager
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.messages import ModelResponse, TextPart
    from services.creation_agent.model_boundary import RecordedAgentModel
    model = await config(2)
    active, maximum = 0, 0
    async def request(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(.03)
        active -= 1
        return ModelResponse(parts=[TextPart('done')])
    monkeypatch.setattr(TestModel, 'request', request)
    @asynccontextmanager
    async def request_stream(*args, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        try:
            yield SimpleNamespace(get=lambda: ModelResponse(parts=[TextPart('done')]), usage=lambda: None, finish_reason=None)
        finally:
            active -= 1
    monkeypatch.setattr(TestModel, 'request_stream', request_stream)
    wrappers = []
    for _ in range(6):
        wrapper = RecordedAgentModel(TestModel(), message=SimpleNamespace(model_snapshot={'id':model.id}, usage={}),
            before_request=AsyncMock(), max_characters=None, manage_context=False)
        for name in ('_finish','_save_response','_save_messages'):
            monkeypatch.setattr(wrapper, name, AsyncMock())
        monkeypatch.setattr(wrapper, '_begin', AsyncMock(return_value=({},0)))
        wrappers.append(wrapper)
    async def invoke(wrapper):
        if streaming:
            async with wrapper.request_stream([], None, None):
                await asyncio.sleep(.03)
        else:
            await wrapper.request([], None, None)
    await asyncio.gather(*(invoke(wrapper) for wrapper in wrappers))
    assert maximum == 2


@pytest.mark.asyncio
async def test_video_capacity_is_held_until_provider_completion(monkeypatch):
    from models.ai_task import AiTask
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.waiting import WaitingForMedia
    model = await config(1)
    executor = AiTaskExecutor()
    calls = []
    async def execute(task, handler):
        calls.append(task.id)
        raise WaitingForMedia({'video_id': 42})
    monkeypatch.setattr(executor, '_execute_handler', execute)
    tasks = [await AiTask.create(task_type=4, status=6, request_params={'workflow_version':'agent-skills-v1',
        'execution_mode':'media', 'operation':'video', 'model_config_id':model.id}) for _ in range(2)]
    await executor.run(tasks[0])
    await executor.run(tasks[1])
    assert calls == [tasks[0].id]
    await tasks[1].refresh_from_db()
    assert tasks[1].status == 6 and tasks[1].stage == 'waiting_capacity'
    await AiTask.filter(id=tasks[0].id).update(status=3)
    await executor.run(tasks[1])
    assert calls == [task.id for task in tasks]
