import asyncio
import pytest

from services.remake.analysis_capacity import AnalysisWindow, current_window, window_for


@pytest.mark.asyncio
async def test_episodes_share_the_model_window_and_foreground_has_priority():
    w = window_for(71)
    assert w is window_for(71) and w is not window_for(72)
    release = asyncio.Event()
    active = []
    async def job(name, draft=False):
        async with w.admit(4, draft=draft):
            assert current_window.get() is w
            active.append(name)
            await release.wait()
    first = [asyncio.create_task(job(name)) for name in ('a','b','c','d')]
    await asyncio.sleep(0)
    queued = [asyncio.create_task(job('draft',True)), asyncio.create_task(job('check'))]
    await asyncio.sleep(0)
    assert active == ['a','b','c','d']
    release.set()
    await asyncio.gather(*first,*queued)
    assert active.index('check') < active.index('draft') and w.width == 4
    assert w.active == 0 and current_window.get() is None


@pytest.mark.asyncio
async def test_rate_feedback_stops_new_admissions_and_old_success_cannot_undo_backoff():
    now = [100.0]
    w = AnalysisWindow(clock=lambda: now[0])
    admitted = asyncio.Event()
    states = []
    async def notify(state):
        states.append(state)
    async def later():
        async with w.admit(8,notify=notify):
            admitted.set()
    async with w.admit(8):
        await w.slow_down(20)
        await w.slow_down(5)
        assert w.width == 4 and w.cooldown_until == 120
        pending = asyncio.create_task(later())
        await asyncio.sleep(0)
        assert not admitted.is_set()
    assert w.width == 4
    now[0] = 121
    async with w.changed:
        w.changed.notify_all()
    await asyncio.wait_for(pending,1)
    assert states == ['waiting_capacity','admitted']


@pytest.mark.asyncio
async def test_cancelled_waiter_releases_queue_and_respects_single_slot():
    w = AnalysisWindow()
    async def waiter():
        async with w.admit(1):
            pytest.fail('cancelled call should never start')
    async with w.admit(1):
        task = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with w.admit(1):
        assert w.active == 1
    assert not w.foreground and not w.background
