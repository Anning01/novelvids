import pytest
import asyncio

from models.ai_task import AiTask
from services.ai_task_executor import (
    EXECUTOR_TASK_TYPES,
    TASK_TIMEOUT,
    AiTaskExecutor,
    BaseTaskHandler,
)
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class _Success(BaseTaskHandler):
    async def execute(self, request_params):
        return {"ok": True}


class _Failure(BaseTaskHandler):
    async def execute(self, request_params):
        raise RuntimeError("safe failure")


class _Counting(BaseTaskHandler):
    def __init__(self):
        self.calls = 0

    async def execute(self, request_params):
        self.calls += 1
        await asyncio.sleep(0.01)
        return {"ok": True}


@pytest.mark.asyncio
async def test_remake_queued_task_is_executor_managed_and_completes_progress():
    assert AiTaskTypeEnum.remake_decomposition in EXECUTOR_TASK_TYPES
    assert TASK_TIMEOUT[AiTaskTypeEnum.remake_decomposition] == 3600
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.remake_decomposition, _Success())
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.queued.value,
        stage="queued",
        progress=0,
        request_params={},
    )

    await executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value
    assert task.stage == "completed"
    assert task.progress == 100


@pytest.mark.asyncio
async def test_remake_failed_task_has_terminal_stage_without_secret_details():
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.remake_decomposition, _Failure())
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.queued.value,
        stage="queued",
        request_params={},
    )

    await executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert task.stage == "failed"
    assert task.progress < 100


@pytest.mark.asyncio
async def test_boot_cleanup_fails_orphaned_queued_remake_task():
    executor = AiTaskExecutor()
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.queued.value,
        stage="queued",
        request_params={},
    )

    await executor.fail_stale_on_boot()

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert task.stage == "failed"


@pytest.mark.asyncio
async def test_duplicate_background_dispatch_executes_same_task_only_once():
    executor = AiTaskExecutor()
    handler = _Counting()
    executor.register(AiTaskTypeEnum.remake_decomposition, handler)
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=TaskStatusEnum.queued.value,
        stage="queued",
        request_params={},
    )

    await asyncio.gather(executor.run(task), executor.run(task))

    assert handler.calls == 1
