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
