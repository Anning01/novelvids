"""为生成视频提取一次性 WebP 海报，避免列表和画布预加载视频本体。"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Literal

from config import settings
from services.cover_derivatives import (
    IMMUTABLE_CACHE_CONTROL,
    local_media_path,
    render_cover_derivatives,
)
from services.oss import normalize_media_url, oss
from services.video.source import VideoSourceError, materialize_video_source


VideoPosterKind = Literal["thumbnail", "preview"]


class VideoPosterError(RuntimeError):
    """视频海报无法提取或持久化。"""


def video_poster_reference(
    video_reference: str | None,
    kind: VideoPosterKind,
) -> str | None:
    if not video_reference or kind not in {"thumbnail", "preview"}:
        return None
    raw = video_reference.split("?", 1)[0]
    prefix = ""
    if raw.startswith("/media/"):
        prefix = "/media/"
        raw = raw[len(prefix) :]
    elif raw.startswith(("./media/", "media/")):
        prefix = "/media/"
        raw = raw.split("media/", 1)[1]
    elif not raw.startswith(("uploads/", "remake/")):
        return None
    path = PurePosixPath(raw)
    if not path.name or path.suffix.lower() not in {".mp4", ".mov", ".webm"}:
        return None
    poster = path.parent / "posters" / f"{path.stem}-{kind}.webp"
    return f"{prefix}{poster.as_posix()}"


class VideoPosterService:
    async def extract_and_store(
        self,
        video_reference: str,
        video_id: int,
    ) -> dict[str, str]:
        stored = normalize_media_url(video_reference) or video_reference
        with TemporaryDirectory(prefix=f"novelvids-poster-{video_id}-") as directory:
            temporary_dir = Path(directory)
            try:
                video_path = await materialize_video_source(
                    stored,
                    temporary_dir / "source.mp4",
                    media_root=Path(settings.MEDIA_PATH),
                    oss_provider=oss,
                )
            except VideoSourceError as exc:
                raise VideoPosterError(str(exc)) from exc
            return await self.extract_file_and_store(video_path, stored, video_id)

    async def extract_file_and_store(
        self,
        video_path: Path,
        video_reference: str,
        video_id: int,
    ) -> dict[str, str]:
        stored = normalize_media_url(video_reference) or video_reference
        references = {
            "poster_thumbnail_url": video_poster_reference(stored, "thumbnail"),
            "poster_url": video_poster_reference(stored, "preview"),
        }
        if not all(references.values()):
            raise VideoPosterError("视频不是受支持的本地或 OSS 媒体引用")

        with TemporaryDirectory(prefix=f"novelvids-poster-frame-{video_id}-") as directory:
            frame_path = Path(directory) / "poster.png"
            await asyncio.to_thread(self._extract_with_ffmpeg, video_path, frame_path)
            frame_bytes = await asyncio.to_thread(frame_path.read_bytes)
            derivatives = await asyncio.to_thread(render_cover_derivatives, frame_bytes)

        if oss.enabled and stored.startswith(("uploads/", "remake/")):
            for kind, data in derivatives.items():
                key = video_poster_reference(stored, kind)
                if key:
                    await oss.put_bytes(
                        key,
                        data,
                        "image/webp",
                        cache_control=IMMUTABLE_CACHE_CONTROL,
                    )
        else:
            media_root = Path(settings.MEDIA_PATH)
            for kind, data in derivatives.items():
                reference = video_poster_reference(stored, kind)
                destination = local_media_path(media_root, reference)
                if destination is None:
                    raise VideoPosterError("视频海报路径无效")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_bytes(data)
                os.replace(temporary, destination)

        return {key: str(value) for key, value in references.items()}

    @staticmethod
    def _extract_with_ffmpeg(video_path: Path, frame_path: Path) -> None:
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            "0.1",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            "1",
            str(frame_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise VideoPosterError("FFmpeg 提取视频海报失败") from exc
        if (
            result.returncode != 0
            or not frame_path.is_file()
            or frame_path.stat().st_size == 0
        ):
            raise VideoPosterError("FFmpeg 提取视频海报失败")


video_poster_service = VideoPosterService()
