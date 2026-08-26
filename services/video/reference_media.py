"""Seedance 参考图片与视频的上传、探测和严格校验。"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, Sequence, TypeVar
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from config import settings
from services.video.capabilities import VideoModelCapabilities


MediaKind = Literal["image", "video"]
ReferenceT = TypeVar("ReferenceT")
REFERENCE_MENTION_PATTERN = re.compile(r"@\{参考(?:图片|视频):[^}]+\}")


def reference_mention_syntax(kind: MediaKind, url: str) -> str:
    """返回编辑器与服务端共享的稳定素材引用语法。"""
    label = "参考图片" if kind == "image" else "参考视频"
    # 与浏览器 encodeURIComponent 保持一致，保证前后端能匹配同一标记。
    encoded_url = quote(url, safe="-_.!~*'()")
    return f"@{{{label}:{encoded_url}}}"


def _reference_mention_url(reference: Any) -> str:
    """Prefer the stable persisted identity when a display URL is signed or renewed."""
    return str(getattr(reference, "mention_url", "") or getattr(reference, "url", ""))


def select_referenced_media(prompt: str, references: Sequence[ReferenceT]) -> list[ReferenceT]:
    """仅保留 prompt 中显式引用的上传素材，并按请求顺序去重。"""
    selected: list[ReferenceT] = []
    seen: set[tuple[str, str]] = set()
    for reference in references:
        kind = str(getattr(reference, "type", ""))
        url = str(getattr(reference, "url", ""))
        if kind not in {"image", "video"} or not url:
            continue
        identity = (kind, url)
        mention_url = _reference_mention_url(reference)
        if identity in seen or reference_mention_syntax(kind, mention_url) not in prompt:
            continue
        seen.add(identity)
        selected.append(reference)
    return selected


def render_reference_mentions(prompt: str, references: Sequence[Any]) -> str:
    """将内部素材标记转换为供应商可读文本，避免泄露媒体 URL。"""
    rendered = prompt
    for index, reference in enumerate(references, start=1):
        kind = str(getattr(reference, "type", ""))
        url = str(getattr(reference, "url", ""))
        if kind not in {"image", "video"} or not url:
            continue
        default_name = f"参考{'图片' if kind == 'image' else '视频'} {index}"
        name = str(getattr(reference, "name", "") or default_name)
        rendered = rendered.replace(
            reference_mention_syntax(kind, _reference_mention_url(reference)),
            f"【参考{'图片' if kind == 'image' else '视频'}：{name}】",
        )
    # 已从素材池删除的旧标记不能作为 URL 或伪引用继续进入供应商 prompt。
    return REFERENCE_MENTION_PATTERN.sub("", rendered)


def media_kind_for_extension(filename: str, capabilities) -> MediaKind:
    """按扩展名判定参考素材类型（OSS 终局端点复用）。"""
    extension = Path(filename).suffix.lower()
    return _media_kind(extension, capabilities)


def _media_kind(extension: str, capabilities: VideoModelCapabilities) -> MediaKind:
    normalized = extension.lstrip(".").lower()
    if normalized in capabilities.reference_image_formats:
        return "image"
    if normalized in capabilities.reference_video_formats:
        return "video"
    raise HTTPException(400, detail="仅支持当前视频模型允许的参考图片或 MP4/MOV 视频")


def _probe(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration,size,format_name:stream=codec_type,codec_name,width,height,duration,avg_frame_rate,r_frame_rate",
                "-of", "json", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise HTTPException(400, detail="无法读取媒体信息，请确认文件没有损坏且编码受支持") from exc
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, detail="无法解析媒体信息") from exc


def _positive_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _fps(stream: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        try:
            rate = float(Fraction(str(value)))
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            return rate
    return 0.0


def _video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    return next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )


def _validate_geometry(width: int, height: int, capabilities: VideoModelCapabilities) -> None:
    if not width or not height:
        raise HTTPException(400, detail="无法读取媒体宽高")
    if not (
        capabilities.reference_media_side_min <= width <= capabilities.reference_media_side_max
        and capabilities.reference_media_side_min <= height <= capabilities.reference_media_side_max
    ):
        raise HTTPException(
            400,
            detail=(
                f"参考媒体宽高必须在 {capabilities.reference_media_side_min}-"
                f"{capabilities.reference_media_side_max}px 之间"
            ),
        )
    ratio = width / height
    if not capabilities.reference_media_ratio_min <= ratio <= capabilities.reference_media_ratio_max:
        raise HTTPException(400, detail="参考媒体宽高比必须在 0.4-2.5 之间")


def _validate_probe(
    kind: MediaKind,
    probe: dict[str, Any],
    size_bytes: int,
    capabilities: VideoModelCapabilities,
) -> dict[str, Any]:
    stream = _video_stream(probe)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    _validate_geometry(width, height, capabilities)
    if kind == "image":
        if size_bytes >= capabilities.reference_image_max_size_mb * 1024 * 1024:
            raise HTTPException(400, detail=f"单张参考图片必须小于 {capabilities.reference_image_max_size_mb}MB")
        return {"width": width, "height": height}

    if size_bytes > capabilities.reference_video_max_size_mb * 1024 * 1024:
        raise HTTPException(400, detail=f"单个参考视频不能超过 {capabilities.reference_video_max_size_mb}MB")
    container_names = {
        value.strip().lower()
        for value in str(probe.get("format", {}).get("format_name") or "").split(",")
    }
    if not container_names.intersection({"mov", "mp4"}):
        raise HTTPException(400, detail="参考视频仅支持 MP4 或 MOV 容器格式")
    pixels = width * height
    if not capabilities.reference_video_pixels_min <= pixels <= capabilities.reference_video_pixels_max:
        raise HTTPException(
            400,
            detail=(
                f"参考视频总像素数必须在 {capabilities.reference_video_pixels_min}-"
                f"{capabilities.reference_video_pixels_max} 之间"
            ),
        )
    codec = str(stream.get("codec_name") or "").lower()
    if codec not in capabilities.reference_video_codecs:
        raise HTTPException(400, detail="参考视频仅支持 H.264/AVC 或 H.265/HEVC 编码")
    audio_codecs = {
        str(item.get("codec_name") or "").lower()
        for item in probe.get("streams", [])
        if item.get("codec_type") == "audio"
    }
    unsupported_audio = audio_codecs.difference(capabilities.reference_video_audio_codecs)
    if unsupported_audio:
        raise HTTPException(400, detail="参考视频音轨仅支持 AAC 或 MP3 编码")
    duration = _positive_float(probe.get("format", {}).get("duration")) or _positive_float(stream.get("duration"))
    if not capabilities.reference_media_duration_min <= duration <= capabilities.reference_video_duration_max:
        raise HTTPException(
            400,
            detail=(
                f"当前模型要求单个参考视频时长为 {capabilities.reference_media_duration_min}-"
                f"{capabilities.reference_video_duration_max} 秒"
            ),
        )
    fps = _fps(stream)
    if not capabilities.reference_video_fps_min <= fps <= capabilities.reference_video_fps_max:
        raise HTTPException(
            400,
            detail=(
                f"参考视频帧率必须在 {capabilities.reference_video_fps_min}-"
                f"{capabilities.reference_video_fps_max} FPS 之间"
            ),
        )
    return {
        "width": width,
        "height": height,
        "duration": round(duration, 3),
        "fps": round(fps, 3),
        "codec": codec,
    }


async def save_reference_upload(
    file: UploadFile,
    capabilities: VideoModelCapabilities,
) -> dict[str, Any]:
    original_name = Path(file.filename or "reference").name
    extension = Path(original_name).suffix.lower()
    kind = _media_kind(extension, capabilities)
    directory = Path(settings.MEDIA_PATH) / "video-references"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    destination = directory / filename
    temporary = directory / f".{filename}.uploading"
    max_bytes = (
        capabilities.reference_image_max_size_mb
        if kind == "image"
        else capabilities.reference_video_max_size_mb
    ) * 1024 * 1024
    size_bytes = 0
    try:
        with temporary.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    label = "图片" if kind == "image" else "视频"
                    raise HTTPException(400, detail=f"单个参考{label}不能超过 {max_bytes // 1024 // 1024}MB")
                target.write(chunk)
        probe = await asyncio.to_thread(_probe, temporary)
        metadata = _validate_probe(kind, probe, size_bytes, capabilities)
        shutil.move(str(temporary), destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {
        "type": kind,
        "url": f"/media/video-references/{filename}",
        "name": original_name,
        "content_type": file.content_type or "",
        "size_bytes": size_bytes,
        **metadata,
    }


def local_reference_path(url: str) -> Path | None:
    prefix = "/media/video-references/"
    if not url.startswith(prefix):
        return None
    filename = Path(url[len(prefix):]).name
    path = Path(settings.MEDIA_PATH) / "video-references" / filename
    if not path.is_file():
        raise HTTPException(400, detail=f"参考素材不存在：{filename}")
    return path


async def verify_local_reference(
    kind: MediaKind,
    url: str,
    capabilities: VideoModelCapabilities,
) -> dict[str, Any] | None:
    path = local_reference_path(url)
    if path is None:
        return None
    extension_kind = _media_kind(path.suffix, capabilities)
    if extension_kind != kind:
        raise HTTPException(400, detail="参考素材类型与文件格式不一致")
    probe = await asyncio.to_thread(_probe, path)
    return _validate_probe(kind, probe, path.stat().st_size, capabilities)
