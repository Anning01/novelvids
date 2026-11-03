"""In-process wakeups for task-scoped event streams.

Streaming followers should read the database when a run appends events or
changes status, not on a fixed timer. Publishers are the creation-agent handler
and the task executor/controllers; the slow fallback timeout keeps followers
correct even when a status change happens in another process.
"""

import asyncio
from contextlib import asynccontextmanager


class TaskSignals:
    """Coalescing per-task broadcast: subscribers wait on an event they own."""

    def __init__(self):
        self._waiters: dict[str, set[asyncio.Event]] = {}

    @asynccontextmanager
    async def subscription(self, key: str):
        event = asyncio.Event()
        waiters = self._waiters.setdefault(key, set())
        waiters.add(event)
        try:
            yield event
        finally:
            waiters.discard(event)
            if not waiters:
                self._waiters.pop(key, None)

    async def publish(self, key: str) -> None:
        for event in list(self._waiters.get(key, ())):
            event.set()

    async def wait(self, event: asyncio.Event, timeout: float) -> bool:
        """Wait for the next wakeup; False when the fallback timeout elapsed."""
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


task_signals = TaskSignals()
