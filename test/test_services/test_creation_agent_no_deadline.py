import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from models.ai_task import AiTask
from schemas.creation_agent import AgentConfiguration
from services.ai_task_executor import AiTaskExecutor, BaseTaskHandler
from utils.enums import AiTaskTypeEnum


class SlowHandler(BaseTaskHandler):
    def timeout_seconds(self, params):
        return 0.001

    async def execute(self, params):
        await asyncio.sleep(0.02)
        return {'completed': True}


@pytest.mark.asyncio
@pytest.mark.parametrize('task_type,versioned', [(7, False), (7, True), (1, True), (3, True)])
async def test_agent_work_continues_past_legacy_deadline(monkeypatch, task_type, versioned):
    executor = AiTaskExecutor()
    handler = SlowHandler()
    executor.register(AiTaskTypeEnum(task_type), handler)
    params = {'agent_configuration': {'timeout_seconds': 600}}
    if versioned:
        params['workflow_version'] = 'agent-skills-v1'
    task = await AiTask.create(task_type=task_type, status=1, request_params=params)
    async def execute(*args):
        return await handler.execute(params)
    monkeypatch.setattr(executor, '_execute_handler', execute)
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert task.response_data == {'completed': True}


@pytest.mark.asyncio
async def test_cleanup_does_not_end_active_agent_due_to_age():
    executor = AiTaskExecutor()
    for task_type, params in [(7, {'agent_configuration': {'timeout_seconds': 600}}),
                              (3, {'workflow_version': 'agent-skills-v1'})]:
        executor.register(AiTaskTypeEnum(task_type), SlowHandler())
        task = await AiTask.create(task_type=task_type, status=2, request_params=params,
            started_at=datetime.now(timezone.utc) - timedelta(days=1))
        await executor.cleanup_stale_tasks(AiTaskTypeEnum(task_type))
        await task.refresh_from_db()
        assert task.status == 2


@pytest.mark.asyncio
async def test_non_agent_jobs_retain_their_existing_timeout(monkeypatch):
    executor = AiTaskExecutor()
    handler = SlowHandler()
    executor.register(AiTaskTypeEnum.storyboard, handler)
    task = await AiTask.create(task_type=3, status=1, request_params={})
    async def execute(*args):
        return await handler.execute({})
    monkeypatch.setattr(executor, '_execute_handler', execute)
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4


@pytest.mark.parametrize('legacy_timeout', [180, 600, 900, None])
def test_old_agent_configuration_no_longer_imposes_a_deadline(legacy_timeout):
    assert AgentConfiguration(timeout_seconds=legacy_timeout).timeout_seconds is None


def test_old_run_caps_are_retired_without_disabling_context_compaction():
    limits = AgentConfiguration(request_limit=20, tool_calls_limit=50, total_tokens_limit=2_000_000,
        working_input_tokens=840000, compaction_trigger_ratio=0.7)
    assert limits.request_limit is None and limits.tool_calls_limit is None and limits.total_tokens_limit is None
    assert limits.working_input_tokens == 840000 and limits.compaction_trigger_ratio == 0.7


@pytest.mark.asyncio
async def test_explicit_stop_interrupts_an_unbounded_model_wait(monkeypatch):
    started, cancelled = asyncio.Event(), asyncio.Event()
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, SlowHandler())
    task = await AiTask.create(task_type=7, status=1, request_params={})
    async def execute(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(executor, '_execute_handler', execute)
    monkeypatch.setattr('services.ai_task_executor.AGENT_CANCEL_POLL_SECONDS', 0.01)
    running = asyncio.create_task(executor.run(task))
    await asyncio.wait_for(started.wait(), 2)
    await AiTask.filter(id=task.id).update(status=5)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    assert cancelled.is_set()
    await task.refresh_from_db()
    assert task.status == 5


@pytest.mark.asyncio
async def test_agent_transport_has_no_request_deadline():
    from types import SimpleNamespace
    from services.creation_agent.handler import configured_model
    model = configured_model(SimpleNamespace(base_url='https://example.invalid/v1', api_key='test-key', model='test', thinking=None), AgentConfiguration())
    try:
        assert model.client.timeout is None
    finally:
        await model.client.close()


@pytest.mark.asyncio
async def test_stopping_an_external_request_keeps_uncertainty_protection(monkeypatch):
    from models.agent_operation import AgentOperation
    from services.creation_agent.operation_receipts import execute_step
    started = asyncio.Event()
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, SlowHandler())
    task = await AiTask.create(task_type=7, status=1, request_params={'workflow_version': 'agent-skills-v1'})
    async def external():
        started.set()
        await asyncio.Event().wait()
    async def execute(*args):
        return await execute_step(task.id, 'model:slow', external, external=True)
    monkeypatch.setattr(executor, '_execute_handler', execute)
    monkeypatch.setattr('services.ai_task_executor.AGENT_CANCEL_POLL_SECONDS', 0.01)
    running = asyncio.create_task(executor.run(task))
    await asyncio.wait_for(started.wait(), 2)
    await AiTask.filter(id=task.id).update(status=5)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, 2)
    await task.refresh_from_db()
    assert task.status == 4 and task.stage == 'needs_review'
    assert (await AgentOperation.get(task=task, key='model:slow')).state == 'uncertain'


@pytest.mark.parametrize('seconds', [None, 1, 30, 60])
def test_legacy_summary_deadline_is_retired(seconds):
    assert AgentConfiguration(summary_timeout_seconds=seconds).summary_timeout_seconds is None


@pytest.mark.asyncio
async def test_agent_reference_generation_disables_synchronous_image_deadline():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch
    from services.creation_agent.skill_execution import current_execution
    from services.reference.generator import generate_for_sora_consistency

    execution = SimpleNamespace(before_request=AsyncMock())
    token = current_execution.set(execution)
    try:
        with patch('services.reference.generator.generate_images', AsyncMock(return_value=[])) as generate:
            await generate_for_sora_consistency({'base_traits': 'test'}, base_url='https://example.invalid', api_key='test')
        assert generate.call_args.kwargs['timeout'] is None
        execution.before_request.assert_awaited_once()
    finally:
        current_execution.reset(token)
