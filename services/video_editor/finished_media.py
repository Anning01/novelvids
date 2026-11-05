"""Private cover storage for completed edits, including existing exports."""
import asyncio
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from fastapi import HTTPException

from utils.messages import localized_message as msg
from services.video_enhancement.media import export_media

_legacy_cover_slots = asyncio.Semaphore(2)


def cover_reference(export_id: int) -> str:
    return f'/media/exports/{export_id}/cover.jpg'


def first_frame(video: Path, cover: Path) -> None:
    try:
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-y', '-threads', '1', '-i', str(video),
            '-map', '0:v:0', '-vf', "scale='min(960,iw)':-2",
            '-frames:v', '1', '-threads', '1', '-q:v', '3', str(cover),
        ], check=True, capture_output=True, timeout=30)
        if not cover.is_file() or not cover.stat().st_size:
            raise ValueError
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError(msg('无法从成片提取第一帧封面')) from None


async def save_cover(export_id: int, video: Path, directory: Path) -> Path:
    temporary = directory / 'first-frame.jpg'
    await asyncio.to_thread(first_frame, video, temporary)
    reference = cover_reference(export_id)
    await export_media.store(reference, temporary)
    return export_media.local_path(reference)


async def get_cover(export) -> Path:
    path = export_media.local_path(cover_reference(export.id))
    if path.is_file():
        return path
    async with _legacy_cover_slots:
        if path.is_file():
            return path
        try:
            async with export_media.materialize(export.media_ref) as video:
                with TemporaryDirectory(prefix='finished-cover-') as directory:
                    return await save_cover(export.id, video, Path(directory))
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
