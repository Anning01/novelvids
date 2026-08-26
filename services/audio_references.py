"""User-uploaded reusable voice reference validation and persistence."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import HTTPException, UploadFile
from tortoise.expressions import Q

from config import settings
from models.audio_reference import AudioReference
from services.oss import make_upload_key, oss


MAX_AUDIO_BYTES = 15 * 1024 * 1024
MIN_AUDIO_DURATION = 1.0
MAX_AUDIO_DURATION = 30.0
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav"}
MAX_TRIM_SOURCE_BYTES = 200 * 1024 * 1024


def audio_reference_accessible(
    reference: AudioReference,
    *,
    team_id: int | None,
    created_by: int | None,
) -> bool:
    """判断音色是否可用于指定项目作用域。

    旧版本中超级管理员上传的音色可能没有 team_id；仅当上传人与项目创建人
    相同时兼容，避免把历史无团队音色放宽给其他项目或团队。
    """
    if reference.source == "system":
        return True
    if reference.team_id is not None:
        return reference.team_id == team_id
    if created_by is not None:
        return reference.created_by == created_by
    return team_id is None and reference.created_by is None


def audio_reference_scope_query(
    *,
    team_id: int | None,
    created_by: int | None,
) -> Q:
    """构造与 ``audio_reference_accessible`` 一致的音色库查询范围。"""
    scope = Q(source="system")
    if team_id is not None:
        scope |= Q(team_id=team_id)
    elif created_by is None:
        scope |= Q(team_id=None, created_by=None)
    if created_by is not None:
        scope |= Q(team_id=None, created_by=created_by)
    return scope


def _validate_extension(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise HTTPException(400, detail="参考音频仅支持 MP3 或 WAV")
    return extension


def _probe_audio(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type,duration", "-of", "json", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        payload = json.loads(result.stdout)
    except (FileNotFoundError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(400, detail="无法读取参考音频，请确认文件没有损坏") from exc
    if not any(stream.get("codec_type") == "audio" for stream in payload.get("streams", [])):
        raise HTTPException(400, detail="上传文件中没有可用音轨")
    try:
        duration = float(payload.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    if duration <= 0:
        raise HTTPException(400, detail="无法读取参考音频时长")
    return round(duration, 3)


async def _validate_audio_file(path: Path) -> float:
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise HTTPException(400, detail="参考音频不能超过 15MB")
    duration = await asyncio.to_thread(_probe_audio, path)
    if not MIN_AUDIO_DURATION <= duration <= MAX_AUDIO_DURATION:
        raise HTTPException(400, detail="参考音频时长必须为 1-30 秒")
    return duration


async def _download_external_audio(url: str, destination: Path) -> None:
    size = 0
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with destination.open("wb") as target:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        size += len(chunk)
                        if size > MAX_TRIM_SOURCE_BYTES:
                            raise HTTPException(400, detail="原音频过大，无法在线裁剪")
                        target.write(chunk)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(400, detail="原音频下载失败，无法在线裁剪") from exc


async def _materialize_reference_audio(reference: AudioReference, destination: Path) -> None:
    raw = reference.audio_url
    if raw.startswith("uploads/") and oss.enabled:
        # OSS 必须使用 Provider 的服务端内网 endpoint。
        await oss.download_to_file(raw, destination)
        return
    if raw.startswith("/media/"):
        media_root = Path(settings.MEDIA_PATH).resolve()
        source = (media_root / raw.removeprefix("/media/")).resolve()
        if media_root not in source.parents or not source.is_file():
            raise HTTPException(404, detail="原音频文件不存在")
        await asyncio.to_thread(shutil.copyfile, source, destination)
        return
    if raw.startswith("http://") or raw.startswith("https://"):
        await _download_external_audio(raw, destination)
        return
    raise HTTPException(400, detail="原音频地址无法裁剪")


def _trim_audio_file(source: Path, destination: Path, *, start: float, duration: float) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
                str(destination),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise HTTPException(500, detail="服务器未安装 ffmpeg，无法裁剪音频") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(400, detail="音频裁剪失败，请确认原文件未损坏") from exc


async def _create_reference(
    *,
    nickname: str,
    gender: str,
    audio_url: str,
    duration: float,
    team_id: int | None,
    created_by: int | None,
) -> AudioReference:
    normalized_nickname = nickname.strip()
    if not normalized_nickname:
        raise HTTPException(400, detail="音色名称不能为空")
    return await AudioReference.create(
        nickname=normalized_nickname,
        gender=gender.strip() or "未设置",
        audio_url=audio_url,
        avatar_url="",
        asset_id=f"upload-{uuid4().hex}",
        source="upload",
        duration=duration,
        team_id=team_id,
        created_by=created_by,
        is_active=True,
    )


async def save_uploaded_audio_reference(
    file: UploadFile,
    *,
    nickname: str,
    gender: str,
    team_id: int | None,
    created_by: int | None,
) -> AudioReference:
    original_name = Path(file.filename or "voice.mp3").name
    extension = _validate_extension(original_name)
    directory = Path(settings.MEDIA_PATH) / "audio-references"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    destination = directory / filename
    temporary = directory / f".{filename}.uploading"
    size = 0
    try:
        with temporary.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise HTTPException(400, detail="参考音频不能超过 15MB")
                target.write(chunk)
        duration = await _validate_audio_file(temporary)
        shutil.move(str(temporary), destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return await _create_reference(
        nickname=nickname,
        gender=gender,
        audio_url=f"/media/audio-references/{filename}",
        duration=duration,
        team_id=team_id,
        created_by=created_by,
    )


async def finalize_oss_audio_reference(
    *,
    key: str,
    filename: str,
    nickname: str,
    gender: str,
    team_id: int | None,
    created_by: int | None,
) -> AudioReference:
    if not oss.enabled:
        raise HTTPException(400, detail="未启用对象存储")
    expected_prefix = f"uploads/{team_id or 0}/"
    if not key.startswith(expected_prefix):
        raise HTTPException(400, detail="参考音频对象不属于当前团队")
    extension = _validate_extension(filename)
    temporary_dir = Path(settings.MEDIA_PATH) / "audio-references" / ".validate"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    temporary = temporary_dir / f"{uuid4().hex}{extension}"
    try:
        # OSS provider uses its internal endpoint here; the signed public URL is never downloaded.
        await oss.download_to_file(key, temporary)
        duration = await _validate_audio_file(temporary)
    finally:
        temporary.unlink(missing_ok=True)
    return await _create_reference(
        nickname=nickname,
        gender=gender,
        audio_url=key,
        duration=duration,
        team_id=team_id,
        created_by=created_by,
    )


async def trim_audio_reference(
    reference: AudioReference,
    *,
    start: float,
    end: float,
    team_id: int | None,
    created_by: int | None,
) -> AudioReference:
    """裁剪用户上传的音色并创建新副本，原音色与已有引用均不受影响。"""
    if reference.source != "upload":
        raise HTTPException(400, detail="系统音色不支持裁剪")
    duration = end - start
    if start < 0 or duration < MIN_AUDIO_DURATION or duration > MAX_AUDIO_DURATION:
        raise HTTPException(400, detail="裁剪片段必须为 1-30 秒")

    temporary_dir = Path(settings.MEDIA_PATH) / "audio-references" / ".trim"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    source = temporary_dir / f"{uuid4().hex}.source"
    output = temporary_dir / f"{uuid4().hex}.wav"
    try:
        await _materialize_reference_audio(reference, source)
        if source.stat().st_size > MAX_TRIM_SOURCE_BYTES:
            raise HTTPException(400, detail="原音频过大，无法在线裁剪")
        source_duration = await asyncio.to_thread(_probe_audio, source)
        if start >= source_duration or end > source_duration + 0.05:
            raise HTTPException(400, detail=f"裁剪范围超出原音频时长 {source_duration:g} 秒")
        await asyncio.to_thread(
            _trim_audio_file,
            source,
            output,
            start=start,
            duration=duration,
        )
        clipped_duration = await _validate_audio_file(output)
        if oss.enabled:
            key = make_upload_key(team_id, f"{Path(reference.asset_id).stem}-trim.wav")
            await oss.put_file(key, output, "audio/wav")
            audio_url = key
        else:
            filename = f"{uuid4().hex}.wav"
            destination = Path(settings.MEDIA_PATH) / "audio-references" / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(output), destination)
            audio_url = f"/media/audio-references/{filename}"
        return await _create_reference(
            nickname=f"{reference.nickname} · 裁剪"[:100],
            gender=reference.gender,
            audio_url=audio_url,
            duration=clipped_duration,
            team_id=team_id,
            created_by=created_by,
        )
    finally:
        source.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
