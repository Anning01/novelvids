"""把本地、OSS 或远程视频安全物化为 FFmpeg 可读取的文件。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit

import httpx


class VideoSourceError(RuntimeError):
    """视频来源不可读。"""


async def materialize_video_source(
    video_ref: str,
    destination: Path,
    *,
    media_root: Path,
    oss_provider,
) -> Path:
    normalized_ref = oss_provider.normalize_media_ref(video_ref)
    if (
        oss_provider.enabled
        and normalized_ref
        and normalized_ref.startswith(("uploads/", "remake/"))
    ):
        await oss_provider.download_to_file(normalized_ref, destination)
        return destination

    local_path = _local_media_path(video_ref, media_root)
    if local_path is not None:
        return local_path

    parsed = urlsplit(video_ref)
    if parsed.scheme not in {"http", "https"}:
        raise VideoSourceError("视频文件不存在")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("GET", video_ref) as response:
                response.raise_for_status()
                with destination.open("wb") as target:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        await asyncio.to_thread(target.write, chunk)
    except httpx.HTTPError as exc:
        raise VideoSourceError("下载视频失败") from exc
    return destination


def _local_media_path(video_ref: str, media_root: Path) -> Path | None:
    raw_path = video_ref.split("?", 1)[0]
    if raw_path.startswith("/media/"):
        relative = raw_path.removeprefix("/media/")
    elif raw_path.startswith(("./media/", "media/")):
        relative = raw_path.split("media/", 1)[1]
    else:
        return None
    root = media_root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise VideoSourceError("本地视频文件不存在")
    return candidate
