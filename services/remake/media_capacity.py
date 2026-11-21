"""Bound native media work across all episode tasks in the worker."""
import asyncio
from contextlib import asynccontextmanager
from config import settings


@asynccontextmanager
async def media_capacity():
    loop = asyncio.get_running_loop()
    slots = getattr(loop, '_remake_media_slots', None)
    if slots is None:
        slots = asyncio.Semaphore(settings.REMAKE_MEDIA_CONCURRENCY)
        loop._remake_media_slots = slots
    async with slots:
        yield


async def finish_thread(function, *args, **kwargs):
    # A cancelled to_thread future does not stop ffmpeg. Keep its work directory and slot until it exits.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
