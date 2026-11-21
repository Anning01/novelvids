"""Speculative shot blocks. Only the ordered confirmation pass publishes downstream dependencies."""
import asyncio

from prompts.remake import shot_continuity


async def confirmed_blocks(count, block_size, *, capacity, language, confirmed, drafts, run, promote, report, audit=None):
    starts = list(range(1, count + 1, block_size))
    first_end = min(block_size, count)
    slots = asyncio.Semaphore(capacity)
    done = len(confirmed)
    failure = None

    async def generate(index, previous, draft):
        nonlocal failure
        async with slots:
            if failure is not None:
                raise failure
            try:
                return await run(index, previous, draft)
            except Exception as exc:
                failure = exc
                raise

    async def mark(index, value):
        nonlocal done
        confirmed[index] = value
        done += 1
        if report:
            await report(done, count)

    async def build(start):
        previous = None
        for i in range(start, min(count + 1, start + block_size)):
            if i in confirmed:
                previous = confirmed[i]
            elif start == 1:
                previous = await generate(i, previous, False)
                await mark(i, previous)
            else:
                if i not in drafts:
                    drafts[i] = await generate(i, previous, True)
                previous = drafts[i]

    # In-flight paid requests must finish before their temporary files are released.
    outcomes = await asyncio.gather(*(build(start) for start in starts), return_exceptions=True)
    for result in outcomes:
        if isinstance(result, BaseException):
            raise result

    for i in range(first_end + 1, count + 1):
        if i in confirmed:
            continue
        previous = confirmed[i - 1]
        if i in starts or i - 1 not in drafts or (
            shot_continuity(previous, i - 1, language) != shot_continuity(drafts[i - 1], i - 1, language)
        ):
            # A short multimodal verdict can keep the draft unchanged, avoiding a whole-block rewrite.
            if audit and await audit(i, previous, drafts[i]):
                value = await promote(i, drafts[i])
            else:
                value = await generate(i, previous, False)
        else:
            value = await promote(i, drafts[i])
        await mark(i, value)
    return [confirmed[i] for i in range(1, count + 1)]
