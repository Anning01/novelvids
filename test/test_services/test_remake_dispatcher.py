import asyncio

import pytest

from services.remake.dispatcher import RemakeTaskDispatcher


class FakeExecutor:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.completed: list[int] = []
        self.failed_dispatches: list[int] = []
        self.raise_for: set[int] = set()

    async def run(self, task):
        if task in self.raise_for:
            raise RuntimeError("dispatch failure")
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.completed.append(task)
        self.active -= 1

    async def fail_dispatch(self, task):
        self.failed_dispatches.append(task)


@pytest.mark.asyncio
async def test_remake_task_dispatcher_limits_project_batch_concurrency():
    executor = FakeExecutor()
    dispatcher = RemakeTaskDispatcher(executor=executor, concurrency=2)

    await dispatcher.run([1, 2, 3, 4, 5])

    assert sorted(executor.completed) == [1, 2, 3, 4, 5]
    assert executor.max_active == 2


@pytest.mark.asyncio
async def test_dispatch_failure_is_isolated_and_marked_for_retry():
    executor = FakeExecutor()
    executor.raise_for = {2}
    dispatcher = RemakeTaskDispatcher(executor=executor, concurrency=2)

    await dispatcher.run([1, 2, 3])

    assert sorted(executor.completed) == [1, 3]
    assert executor.failed_dispatches == [2]
