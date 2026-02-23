import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock

import pytest

from models.ai_task import AiTask
from models.config import AiModelConfig
from services.ai_task_executor import (
    AiTaskExecutor,
    BaseTaskHandler,
    TASK_TIMEOUT,
    ai_task_executor,
)
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


# ---- 测试用 Handler ----

class SuccessHandler(BaseTaskHandler):
    """始终成功的处理器。"""

    async def execute(self, request_params: dict) -> dict:
        return {"result": "ok", "echo": request_params}


class SlowHandler(BaseTaskHandler):
    """执行缓慢的处理器，用于超时测试。"""

    async def execute(self, request_params: dict) -> dict:
        await asyncio.sleep(999)
        return {"result": "should not reach"}


class FailHandler(BaseTaskHandler):
    """始终失败的处理器。"""

    async def execute(self, request_params: dict) -> dict:
        raise RuntimeError("任务执行出错")


class CountingHandler(BaseTaskHandler):
    """记录并发数的处理器。"""

    def __init__(self):
        self.max_concurrent = 0
        self.current = 0
        self._lock = asyncio.Lock()

    async def execute(self, request_params: dict) -> dict:
        async with self._lock:
            self.current += 1
            if self.current > self.max_concurrent:
                self.max_concurrent = self.current
        await asyncio.sleep(0.05)
        async with self._lock:
            self.current -= 1
        return {"ok": True}


# =====================================================================
# submit：提交任务
# =====================================================================

@pytest.mark.asyncio
async def test_submit_创建pending任务():
    """submit 应在数据库中创建 pending 状态的任务。"""
    executor = AiTaskExecutor()
    task = await executor.submit(
        AiTaskTypeEnum.extraction,
        {"chapter_id": 1, "novel_id": 1},
    )

    assert task.id is not None
    assert task.status == TaskStatusEnum.pending.value
    assert task.task_type == AiTaskTypeEnum.extraction.value
    assert task.request_params["chapter_id"] == 1


# =====================================================================
# run：正常执行
# =====================================================================

@pytest.mark.asyncio
async def test_run_正常完成():
    """正常执行任务，状态变为 completed，结果写入 response_data。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, SuccessHandler())

    task = await executor.submit(
        AiTaskTypeEnum.extraction, {"chapter_id": 1}
    )
    await executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value
    assert task.response_data["result"] == "ok"
    assert task.started_at is not None
    assert task.finished_at is not None


@pytest.mark.asyncio
async def test_run_未注册处理器_标记失败():
    """未注册处理器的任务类型应直接标记为 failed。"""
    executor = AiTaskExecutor()  # 不注册任何 handler

    task = await executor.submit(
        AiTaskTypeEnum.video, {"data": 1}
    )
    await executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert "未注册" in task.error_message


@pytest.mark.asyncio
async def test_run_执行异常_标记失败():
    """执行过程中抛出异常应标记为 failed 并记录错误信息。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, FailHandler())

    task = await executor.submit(
        AiTaskTypeEnum.extraction, {"chapter_id": 1}
    )
    await executor.run(task)

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert "任务执行出错" in task.error_message


@pytest.mark.asyncio
async def test_run_超时_标记失败():
    """执行超时的任务应被标记为 failed。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, SlowHandler())

    task = await executor.submit(
        AiTaskTypeEnum.extraction, {"chapter_id": 1}
    )

    # 临时设置很短的超时
    original_timeout = TASK_TIMEOUT[AiTaskTypeEnum.extraction]
    TASK_TIMEOUT[AiTaskTypeEnum.extraction] = 0.1

    try:
        await executor.run(task)
    finally:
        TASK_TIMEOUT[AiTaskTypeEnum.extraction] = original_timeout

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed.value
    assert "超时" in task.error_message


@pytest.mark.asyncio
async def test_run_已取消任务_跳过执行():
    """任务在排队时被用户取消，run 时应跳过。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, SuccessHandler())

    task = await executor.submit(
        AiTaskTypeEnum.extraction, {"chapter_id": 1}
    )

    # 模拟用户取消
    task.status = TaskStatusEnum.cancelled.value
    await task.save(update_fields=["status"])

    await executor.run(task)

    await task.refresh_from_db()
    # 状态应保持 cancelled，不会变成 completed
    assert task.status == TaskStatusEnum.cancelled.value


# =====================================================================
# cleanup_stale_tasks：清理超时任务
# =====================================================================

@pytest.mark.asyncio
async def test_cleanup_清理超时running任务():
    """超时的 running 任务应被标记为 failed。"""
    executor = AiTaskExecutor()

    stale = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": 1},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=120),
    )

    await executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

    await stale.refresh_from_db()
    assert stale.status == TaskStatusEnum.failed.value
    assert "异常任务清理" in stale.error_message


@pytest.mark.asyncio
async def test_cleanup_清理超时pending任务():
    """超时的 pending 任务（一直没执行）也应被清理。"""
    executor = AiTaskExecutor()

    stale = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.pending.value,
        request_params={"chapter_id": 1},
    )
    # 手动设置 created_at 为很久以前
    stale.created_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    await stale.save(update_fields=["created_at"])

    await executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

    await stale.refresh_from_db()
    assert stale.status == TaskStatusEnum.failed.value


@pytest.mark.asyncio
async def test_cleanup_不清理正常任务():
    """未超时的 running 任务不应被清理。"""
    executor = AiTaskExecutor()

    fresh = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.running.value,
        request_params={"chapter_id": 1},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    )

    await executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

    await fresh.refresh_from_db()
    assert fresh.status == TaskStatusEnum.running.value  # 仍然 running


@pytest.mark.asyncio
async def test_cleanup_不影响已完成任务():
    """已经 completed 的任务不应被清理。"""
    executor = AiTaskExecutor()

    completed = await AiTask.create(
        task_type=AiTaskTypeEnum.extraction.value,
        status=TaskStatusEnum.completed.value,
        request_params={"chapter_id": 1},
        response_data={"result": "ok"},
    )

    await executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

    await completed.refresh_from_db()
    assert completed.status == TaskStatusEnum.completed.value


@pytest.mark.asyncio
async def test_cleanup_不影响其他任务类型():
    """清理 extraction 类型不影响 video 类型的超时任务。"""
    executor = AiTaskExecutor()

    video_stale = await AiTask.create(
        task_type=AiTaskTypeEnum.video.value,
        status=TaskStatusEnum.running.value,
        request_params={"data": 1},
        started_at=datetime.now(timezone.utc) - timedelta(seconds=999),
    )

    # 只清理 extraction
    await executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

    await video_stale.refresh_from_db()
    assert video_stale.status == TaskStatusEnum.running.value  # video 不受影响


# =====================================================================
# submit_and_run：提交并执行
# =====================================================================

@pytest.mark.asyncio
async def test_submit_and_run_完整流程():
    """submit_and_run 应提交并执行任务，最终状态为 completed。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, SuccessHandler())

    task = await executor.submit_and_run(
        AiTaskTypeEnum.extraction, {"chapter_id": 1}
    )

    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value
    assert task.response_data is not None


# =====================================================================
# get_semaphore：并发信号量
# =====================================================================

@pytest.mark.asyncio
async def test_get_semaphore_创建和复用():
    """同类型同并发数应复用同一个信号量。"""
    executor = AiTaskExecutor()

    sem1 = executor.get_semaphore(AiTaskTypeEnum.extraction, 3)
    sem2 = executor.get_semaphore(AiTaskTypeEnum.extraction, 3)
    assert sem1 is sem2  # 同一对象

    # 不同并发数应创建新的
    sem3 = executor.get_semaphore(AiTaskTypeEnum.extraction, 5)
    assert sem3 is not sem1


@pytest.mark.asyncio
async def test_get_semaphore_不同类型独立():
    """不同任务类型的信号量互相独立。"""
    executor = AiTaskExecutor()

    sem_ext = executor.get_semaphore(AiTaskTypeEnum.extraction, 3)
    sem_vid = executor.get_semaphore(AiTaskTypeEnum.video, 3)
    assert sem_ext is not sem_vid


# =====================================================================
# 多任务执行场景
# =====================================================================

@pytest.mark.asyncio
async def test_连续执行多个任务():
    """按顺序执行多个任务，全部成功。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, SuccessHandler())

    tasks = []
    for i in range(3):
        t = await executor.submit(
            AiTaskTypeEnum.extraction, {"chapter_id": i + 1}
        )
        tasks.append(t)

    for t in tasks:
        await executor.run(t)

    for t in tasks:
        await t.refresh_from_db()
        assert t.status == TaskStatusEnum.completed.value


@pytest.mark.asyncio
async def test_部分任务失败_不影响其他():
    """一个任务失败不影响后续任务的执行。"""
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, FailHandler())
    executor.register(AiTaskTypeEnum.video, SuccessHandler())

    fail_task = await executor.submit(
        AiTaskTypeEnum.extraction, {"chapter_id": 1}
    )
    success_task = await executor.submit(
        AiTaskTypeEnum.video, {"data": 1}
    )

    await executor.run(fail_task)
    await executor.run(success_task)

    await fail_task.refresh_from_db()
    assert fail_task.status == TaskStatusEnum.failed.value

    await success_task.refresh_from_db()
    assert success_task.status == TaskStatusEnum.completed.value
