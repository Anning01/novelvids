"""Concurrent shot blocks with ordered, streaming confirmation of their boundaries."""
import asyncio
from contextlib import nullcontext

from prompts.remake import shot_continuity
from services.remake.analysis_capacity import provider_pressure


async def confirmed_blocks(count, block_size, *, capacity, language, confirmed, drafts, run, promote, report, audit=None):
    starts = range(1, count + 1, block_size)
    first_end = min(block_size, count)
    slots = asyncio.Semaphore(capacity) if capacity is not None else None
    ready = {i: asyncio.Event() for i in range(1, count + 1)}
    done = len(confirmed)
    fatal = None
    block_errors = {}

    async def model_step(fn, *args):
        nonlocal fatal
        async with slots if slots is not None else nullcontext():
            if fatal is not None:
                raise fatal
            try:
                return await fn(*args)
            except Exception as exc:
                if not provider_pressure(exc):
                    fatal = exc
                raise

    async def mark(index, value):
        nonlocal done
        confirmed[index] = value
        done += 1
        if report:
            await report(done, count)

    async def build(start):
        nonlocal fatal
        previous = None
        indices = range(start, min(count + 1, start + block_size))
        try:
            for i in indices:
                if i in confirmed:
                    previous = drafts.get(i, confirmed[i])
                elif start == 1:
                    previous = await model_step(run, i, previous, False)
                    await mark(i, previous)
                else:
                    if i not in drafts:
                        drafts[i] = await model_step(run, i, previous, True)
                    previous = drafts[i]
                ready[i].set()
        except BaseException as exc:
            block_errors[start] = exc
            if not provider_pressure(exc):
                fatal = fatal or exc
            raise
        finally:
            for i in indices:
                ready[i].set()

    async def confirm():
        # Only wait for this cut and its predecessor; a slow unrelated block must not delay review.
        await ready[first_end].wait()
        for i in range(first_end + 1, count + 1):
            await ready[i].wait()
            if i in confirmed:
                continue
            if fatal is not None:
                raise fatal
            if i - 1 not in confirmed:
                raise block_errors[1 + (i - 2) // block_size * block_size]
            if i not in drafts:
                raise block_errors[1 + (i - 1) // block_size * block_size]
            previous = confirmed[i - 1]
            candidate = drafts[i]
            recheck = i in starts or i - 1 not in drafts or (
                shot_continuity(previous, i - 1, language) != shot_continuity(drafts[i - 1], i - 1, language)
            )
            if recheck and (not audit or not await model_step(audit, i, previous, candidate)):
                value = await model_step(run, i, previous, False)
            else:
                value = await promote(i, candidate)
            await mark(i, value)

    # Let accepted calls finish or checkpoint even if a different block fails.
    results = await asyncio.gather(*(build(start) for start in starts), confirm(), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return [confirmed[i] for i in range(1, count + 1)]
