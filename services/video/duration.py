"""Measured media duration is distinct from the requested generation duration."""

import asyncio
import math
from pathlib import Path

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from models.video import Video
from services.oss import normalize_media_url
from services.video.reference_media import _probe, _video_stream
from utils.messages import localized_message


def measure_video_duration(path: Path) -> float:
    raw = _probe(path)
    duration = float(raw.get('format', {}).get('duration') or _video_stream(raw).get('duration') or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(localized_message('无法读取视频实际时长'))
    return duration


async def generated_video_duration(video: Video) -> float:
    reference = normalize_media_url(video.url) or video.url
    metadata = video.metadata or {}
    measured = metadata.get('duration_seconds')
    if metadata.get('duration_source_ref') == reference and isinstance(measured, (int, float)) and math.isfinite(measured) and measured > 0:
        return float(measured)
    from services.video_editor.assets import editor_storage
    async with editor_storage.materialize(reference) as path:
        duration = await asyncio.to_thread(measure_video_duration, path)
    # Merge the probe cache without replacing concurrent poster or task updates.
    async with in_transaction():
        current = await Video.filter(id=video.id).select_for_update().get()
        if current.url != video.url:
            raise HTTPException(409, localized_message('视频来源已变化，请重新读取'))
        current.metadata = {**(current.metadata or {}), 'duration_seconds': duration, 'duration_source_ref': reference}
        await current.save(update_fields=['metadata'])
        video.metadata = current.metadata
    return duration
