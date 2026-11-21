"""Admission shared by all remake episodes using one analysis model in this worker."""
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from contextvars import ContextVar
from time import monotonic

# Transport-level admission rejections also feed the window when the HTTP client waits internally.
current_window = ContextVar("remake_analysis_window", default=None)


def provider_pressure(error):
    text = str(error).lower()
    return (getattr(error, "status_code", None) == 429
            or getattr(error, "error_code", None) in {"REMAKE_ANALYSIS_RATE_LIMITED", "REMAKE_ANALYSIS_PROVIDER_UNAVAILABLE"}
            or "request burst" in text
            or "unable to handle additional requests due to server overload" in text)


class AnalysisWindow:
    def __init__(self, *, clock=monotonic):
        self.clock = clock
        self.changed = asyncio.Condition()
        self.foreground = deque()
        self.background = deque()
        self.active = 0
        self.width = 2
        self.successes = 0
        self.epoch = 0
        self.cooldown_until = 0.0
        self.last_finish = 0.0

    async def slow_down(self, delay):
        async with self.changed:
            now = self.clock()
            if now >= self.cooldown_until:
                self.width = max(1, self.width // 2)
                self.epoch += 1
            self.cooldown_until = max(self.cooldown_until, now + delay)
            self.successes = 0
            self.changed.notify_all()

    @asynccontextmanager
    async def admit(self, ceiling, *, draft=False, notify=None):
        token = object()
        queue = self.background if draft else self.foreground
        admitted = notified = success = False
        epoch = 0
        async with self.changed:
            if not self.active and not self.foreground and not self.background and self.clock() - self.last_finish > 60:
                self.width, self.successes = 2, 0
            queue.append(token)
        try:
            while not admitted:
                async with self.changed:
                    delay = self.cooldown_until - self.clock()
                    first = (self.foreground or self.background)[0]
                    if first is token and self.active < min(ceiling, self.width) and delay <= 0:
                        queue.popleft()
                        self.active += 1
                        admitted, epoch = True, self.epoch
                        self.changed.notify_all()
                    elif notified or not notify:
                        try:
                            if delay > 0:
                                await asyncio.wait_for(self.changed.wait(), delay)
                            else:
                                await self.changed.wait()
                        except TimeoutError:
                            pass
                        continue
                if not admitted and notify and not notified:
                    notified = True
                    await notify("waiting_capacity")
            if notified:
                await notify("admitted")
            handle = current_window.set(self)
            try:
                yield
                success = True
            finally:
                current_window.reset(handle)
        finally:
            async with self.changed:
                if admitted:
                    self.active -= 1
                    self.last_finish = self.clock()
                    if success and epoch == self.epoch and self.width < ceiling and self.last_finish >= self.cooldown_until:
                        self.successes += 1
                        if self.successes >= self.width:
                            self.width += 1
                            self.successes = 0
                else:
                    queue.remove(token)
                self.changed.notify_all()


def window_for(model_id):
    loop = asyncio.get_running_loop()
    windows = getattr(loop, '_remake_analysis_windows', None)
    if windows is None:
        windows = loop._remake_analysis_windows = {}
    if model_id not in windows:
        windows[model_id] = AnalysisWindow()
    return windows[model_id]
