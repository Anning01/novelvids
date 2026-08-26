from io import BytesIO
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import HTTPException, UploadFile

from services.audio_references import (
    audio_reference_accessible,
    finalize_oss_audio_reference,
    save_uploaded_audio_reference,
    trim_audio_reference,
)
from models.audio_reference import AudioReference


@pytest.mark.asyncio
async def test_本地上传音频落库为媒体路径(monkeypatch, tmp_path):
    monkeypatch.setattr("services.audio_references.settings.MEDIA_PATH", str(tmp_path))
    validate = AsyncMock(return_value=4.25)
    monkeypatch.setattr("services.audio_references._validate_audio_file", validate)
    upload = UploadFile(filename="角色声音.WAV", file=BytesIO(b"wave-bytes"))

    reference = await save_uploaded_audio_reference(
        upload,
        nickname="  羽宁音色  ",
        gender="女",
        team_id=7,
        created_by=9,
    )

    assert reference.nickname == "羽宁音色"
    assert reference.audio_url.startswith("/media/audio-references/")
    assert reference.audio_url.endswith(".wav")
    assert reference.duration == 4.25
    assert reference.source == "upload"
    assert reference.team_id == 7
    assert (tmp_path / reference.audio_url.removeprefix("/media/")).read_bytes() == b"wave-bytes"


@pytest.mark.asyncio
async def test_音频库允许保存seedance25的30秒内音频(monkeypatch, tmp_path):
    monkeypatch.setattr("services.audio_references.settings.MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(
        "services.audio_references._validate_audio_file",
        AsyncMock(return_value=29.9),
    )
    upload = UploadFile(filename="long.mp3", file=BytesIO(b"long-audio"))

    reference = await save_uploaded_audio_reference(
        upload,
        nickname="长音色",
        gender="未设置",
        team_id=7,
        created_by=9,
    )

    assert reference.duration == 29.9


@pytest.mark.asyncio
async def test_oss音频使用当前团队对象并经内网校验(monkeypatch, tmp_path):
    download = AsyncMock()
    fake_oss = SimpleNamespace(enabled=True, download_to_file=download)
    monkeypatch.setattr("services.audio_references.oss", fake_oss)
    monkeypatch.setattr("services.audio_references.settings.MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(
        "services.audio_references._validate_audio_file",
        AsyncMock(return_value=6.5),
    )

    reference = await finalize_oss_audio_reference(
        key="uploads/7/20260825/voice.mp3",
        filename="voice.mp3",
        nickname="旁白",
        gender="男",
        team_id=7,
        created_by=9,
    )

    assert reference.audio_url == "uploads/7/20260825/voice.mp3"
    assert reference.duration == 6.5
    download.assert_awaited_once()


@pytest.mark.asyncio
async def test_oss音频拒绝跨团队对象(monkeypatch):
    monkeypatch.setattr(
        "services.audio_references.oss",
        SimpleNamespace(enabled=True, download_to_file=AsyncMock()),
    )

    with pytest.raises(HTTPException, match="不属于当前团队"):
        await finalize_oss_audio_reference(
            key="uploads/8/20260825/voice.mp3",
            filename="voice.mp3",
            nickname="旁白",
            gender="男",
            team_id=7,
            created_by=9,
        )


@pytest.mark.asyncio
async def test_音色访问范围兼容同一创建人但不放宽给其他创建人():
    reference = await AudioReference.create(
        nickname="历史音色",
        gender="男",
        audio_url="https://cdn.example.com/legacy.mp3",
        avatar_url="",
        asset_id="legacy-unscoped",
        source="upload",
        team_id=None,
        created_by=9,
        is_active=True,
    )

    assert audio_reference_accessible(reference, team_id=7, created_by=9) is True
    assert audio_reference_accessible(reference, team_id=7, created_by=10) is False


@pytest.mark.asyncio
async def test_本地音色裁剪创建新副本且保留原文件(monkeypatch, tmp_path):
    media_root = tmp_path / "media"
    source = media_root / "audio-references" / "long.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"original-audio")
    reference = await AudioReference.create(
        nickname="长音色",
        gender="女",
        audio_url="/media/audio-references/long.mp3",
        avatar_url="",
        asset_id="upload-long",
        source="upload",
        duration=60,
        team_id=7,
        created_by=9,
        is_active=True,
    )
    monkeypatch.setattr("services.audio_references.settings.MEDIA_PATH", str(media_root))
    monkeypatch.setattr("services.audio_references._probe_audio", lambda _: 60.0)
    monkeypatch.setattr(
        "services.audio_references._trim_audio_file",
        lambda _source, destination, **_: destination.write_bytes(b"trimmed-audio"),
    )
    monkeypatch.setattr(
        "services.audio_references._validate_audio_file",
        AsyncMock(return_value=12.0),
    )

    clipped = await trim_audio_reference(
        reference,
        start=8,
        end=20,
        team_id=7,
        created_by=9,
    )

    assert clipped.id != reference.id
    assert clipped.nickname == "长音色 · 裁剪"
    assert clipped.duration == 12
    assert clipped.audio_url.startswith("/media/audio-references/")
    assert source.read_bytes() == b"original-audio"
    assert (media_root / clipped.audio_url.removeprefix("/media/")).read_bytes() == b"trimmed-audio"


@pytest.mark.asyncio
async def test_oss音色裁剪通过内网下载并上传副本(monkeypatch, tmp_path):
    async def download(_key, destination):
        destination.write_bytes(b"oss-source")

    fake_oss = SimpleNamespace(
        enabled=True,
        download_to_file=AsyncMock(side_effect=download),
        put_file=AsyncMock(),
    )
    reference = await AudioReference.create(
        nickname="OSS 长音色",
        gender="男",
        audio_url="uploads/7/voice.mp3",
        avatar_url="",
        asset_id="upload-oss-long",
        source="upload",
        duration=45,
        team_id=7,
        created_by=9,
        is_active=True,
    )
    monkeypatch.setattr("services.audio_references.oss", fake_oss)
    monkeypatch.setattr("services.audio_references.settings.MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr("services.audio_references._probe_audio", lambda _: 45.0)
    monkeypatch.setattr(
        "services.audio_references._trim_audio_file",
        lambda _source, destination, **_: destination.write_bytes(b"trimmed"),
    )
    monkeypatch.setattr(
        "services.audio_references._validate_audio_file",
        AsyncMock(return_value=15.0),
    )

    clipped = await trim_audio_reference(
        reference,
        start=5,
        end=20,
        team_id=7,
        created_by=9,
    )

    fake_oss.download_to_file.assert_awaited_once_with("uploads/7/voice.mp3", ANY)
    fake_oss.put_file.assert_awaited_once()
    assert clipped.audio_url.startswith("uploads/7/")
