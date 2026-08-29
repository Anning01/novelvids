from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exceptions.remake import RemakeError


MAX_REMAKE_BYTES = 500 * 1024 * 1024
MAX_REMAKE_DURATION_SECONDS = 1200.0
ALLOWED_REMAKE_EXTENSIONS = {".mp4", ".mov"}
ALLOWED_CONTAINER_NAMES = {"mov", "mp4"}


@dataclass(frozen=True)
class ValidatedRemakeMedia:
    original_filename: str
    mime_type: str | None
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    container_format: str
    checksum: str


def _run_ffprobe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def _positive_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class RemakeMediaValidator:
    """来源视频扩展名、字节、真实容器、时长和视频流校验器。"""

    @staticmethod
    def validate_extension(filename: str) -> None:
        extension = Path(Path(filename).name).suffix.lower()
        if extension not in ALLOWED_REMAKE_EXTENSIONS:
            raise RemakeError(
                422,
                "REMAKE_MEDIA_EXTENSION_UNSUPPORTED",
                "来源视频仅支持 MP4 或 MOV 格式",
                context={"filename": Path(filename).name},
            )

    @classmethod
    def validate_probe(
        cls,
        *,
        original_filename: str,
        size_bytes: int,
        probe: dict[str, Any],
        checksum: str,
        mime_type: str | None = None,
    ) -> ValidatedRemakeMedia:
        cls.validate_extension(original_filename)
        if size_bytes <= 0:
            raise RemakeError(422, "REMAKE_MEDIA_INVALID_CONTAINER", "来源视频为空或无法读取")
        if size_bytes > MAX_REMAKE_BYTES:
            raise RemakeError(
                413,
                "REMAKE_MEDIA_SIZE_EXCEEDED",
                "单个来源视频不能超过500MB",
                context={"filename": Path(original_filename).name, "limit_bytes": MAX_REMAKE_BYTES},
            )

        container_names = {
            item.strip().lower()
            for item in str(probe.get("format", {}).get("format_name") or "").split(",")
            if item.strip()
        }
        if not container_names.intersection(ALLOWED_CONTAINER_NAMES):
            raise RemakeError(
                422,
                "REMAKE_MEDIA_INVALID_CONTAINER",
                "文件不是有效的 MP4/MOV 视频或已经损坏",
                context={"filename": Path(original_filename).name},
            )

        video_stream = next(
            (
                stream
                for stream in probe.get("streams", [])
                if stream.get("codec_type") == "video"
            ),
            None,
        )
        if video_stream is None:
            raise RemakeError(
                422,
                "REMAKE_MEDIA_VIDEO_STREAM_MISSING",
                "来源文件中没有有效视频流",
                context={"filename": Path(original_filename).name},
            )
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        if width <= 0 or height <= 0:
            raise RemakeError(
                422,
                "REMAKE_MEDIA_INVALID_CONTAINER",
                "无法读取来源视频画面尺寸",
                context={"filename": Path(original_filename).name},
            )

        duration = _positive_float(probe.get("format", {}).get("duration"))
        if not duration:
            duration = _positive_float(video_stream.get("duration"))
        if duration <= 0:
            raise RemakeError(
                422,
                "REMAKE_MEDIA_DURATION_INVALID",
                "无法读取来源视频时长",
                context={"filename": Path(original_filename).name},
            )
        if duration > MAX_REMAKE_DURATION_SECONDS:
            raise RemakeError(
                422,
                "REMAKE_MEDIA_DURATION_EXCEEDED",
                "视频时长不能超过20分钟",
                context={
                    "filename": Path(original_filename).name,
                    "limit_seconds": MAX_REMAKE_DURATION_SECONDS,
                },
            )

        extension = Path(original_filename).suffix.lower()
        return ValidatedRemakeMedia(
            original_filename=Path(original_filename).name,
            mime_type=mime_type,
            size_bytes=size_bytes,
            duration_seconds=round(duration, 3),
            width=width,
            height=height,
            container_format=extension.lstrip("."),
            checksum=checksum,
        )

    def validate_path(
        self,
        path: Path,
        *,
        original_filename: str,
        mime_type: str | None = None,
    ) -> ValidatedRemakeMedia:
        self.validate_extension(original_filename)
        try:
            size_bytes = path.stat().st_size
            if size_bytes > MAX_REMAKE_BYTES:
                raise RemakeError(
                    413,
                    "REMAKE_MEDIA_SIZE_EXCEEDED",
                    "单个来源视频不能超过500MB",
                    context={"filename": Path(original_filename).name, "limit_bytes": MAX_REMAKE_BYTES},
                )
            probe = _run_ffprobe(path)
            checksum = _sha256(path)
        except RemakeError:
            raise
        except Exception as error:
            raise RemakeError(
                422,
                "REMAKE_MEDIA_INVALID_CONTAINER",
                "文件不是有效的 MP4/MOV 视频或已经损坏",
                context={"filename": Path(original_filename).name},
            ) from error
        return self.validate_probe(
            original_filename=original_filename,
            size_bytes=size_bytes,
            probe=probe,
            checksum=checksum,
            mime_type=mime_type,
        )
