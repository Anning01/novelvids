from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi import UploadFile

from exceptions.remake import RemakeError
from models.remake_upload import RemakeUpload
from services.remake.media import ValidatedRemakeMedia
from services.remake.uploads import RemakeUploadService


class FakeValidator:
    def validate_extension(self, filename: str) -> None:
        if not filename.endswith(".mp4"):
            raise RemakeError(422, "REMAKE_MEDIA_EXTENSION_UNSUPPORTED", "bad")

    def validate_path(self, path, *, original_filename, mime_type=None):
        return ValidatedRemakeMedia(
            original_filename=original_filename,
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            duration_seconds=12.5,
            width=1920,
            height=1080,
            container_format="mp4",
            checksum="c" * 64,
        )


class LocalProvider:
    enabled = False
    name = "local"


class OssProvider:
    enabled = True
    name = "oss"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


def make_upload(content: bytes = b"video") -> UploadFile:
    return UploadFile(
        filename="demo.mp4",
        file=BytesIO(content),
        headers={"content-type": "video/mp4"},
    )


@pytest.mark.asyncio
async def test_local_upload_streams_to_ready_staging_record(tmp_path):
    service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )

    upload = await service.stage_local(make_upload(), team_id=9, user_id=7)

    assert upload.status == "ready"
    assert upload.team_id == 9
    assert upload.created_by == 7
    assert upload.duration_seconds == 12.5
    assert (tmp_path / upload.object_key).read_bytes() == b"video"


@pytest.mark.asyncio
async def test_local_upload_aborts_and_cleans_partial_file_when_stream_limit_is_crossed(
    tmp_path,
):
    service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
        max_bytes=4,
    )

    with pytest.raises(RemakeError) as exc_info:
        await service.stage_local(make_upload(b"12345"), team_id=None, user_id=None)

    assert exc_info.value.error_code == "REMAKE_MEDIA_SIZE_EXCEEDED"
    failed = await RemakeUpload.get()
    assert failed.status == "failed"
    assert not (tmp_path / failed.object_key).exists()


@pytest.mark.asyncio
async def test_upload_ownership_expiry_and_one_time_commit_are_enforced(tmp_path):
    service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await service.stage_local(make_upload(), team_id=9, user_id=7)

    with pytest.raises(RemakeError) as forbidden:
        await service.get_ready(upload.id, team_id=9, user_id=8)
    assert forbidden.value.error_code == "REMAKE_UPLOAD_NOT_FOUND"

    upload.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await upload.save(update_fields=["expires_at", "updated_at"])
    with pytest.raises(RemakeError) as expired:
        await service.get_ready(upload.id, team_id=9, user_id=7)
    assert expired.value.error_code == "REMAKE_UPLOAD_EXPIRED"

    upload.status = "committed"
    await upload.save(update_fields=["status", "updated_at"])
    with pytest.raises(RemakeError) as committed:
        await service.release(upload.id, team_id=9, user_id=7)
    assert committed.value.error_code == "REMAKE_UPLOAD_ALREADY_COMMITTED"


@pytest.mark.asyncio
async def test_release_removes_uncommitted_local_record_and_file(tmp_path):
    service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    upload = await service.stage_local(make_upload(), team_id=None, user_id=None)
    path = tmp_path / upload.object_key

    await service.release(upload.id, team_id=None, user_id=None)

    assert not path.exists()
    assert await RemakeUpload.filter(id=upload.id).count() == 0


@pytest.mark.asyncio
async def test_cleanup_expired_uploads_deletes_media_but_preserves_committed_sources(
    tmp_path,
):
    service = RemakeUploadService(
        validator=FakeValidator(),
        provider=LocalProvider(),
        media_root=tmp_path,
    )
    expired = await service.stage_local(make_upload(b"expired"), team_id=9, user_id=7)
    committed = await service.stage_local(make_upload(b"committed"), team_id=9, user_id=7)
    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await expired.save(update_fields=["expires_at", "updated_at"])
    committed.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    committed.status = "committed"
    await committed.save(update_fields=["expires_at", "status", "updated_at"])
    expired_path = tmp_path / expired.object_key
    committed_path = tmp_path / committed.object_key

    first = await service.cleanup_expired()
    second = await service.cleanup_expired()

    await expired.refresh_from_db()
    await committed.refresh_from_db()
    assert first == 1
    assert second == 0
    assert expired.status == "expired"
    assert not expired_path.exists()
    assert committed.status == "committed"
    assert committed_path.exists()


@pytest.mark.asyncio
async def test_cleanup_expired_oss_upload_deletes_only_uncommitted_object(tmp_path):
    provider = OssProvider()
    service = RemakeUploadService(
        validator=FakeValidator(),
        provider=provider,
        media_root=tmp_path,
    )
    expired = await RemakeUpload.create(
        storage_provider="oss",
        object_key="remake/sources/expired.mp4",
        original_filename="expired.mp4",
        status="ready",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    committed = await RemakeUpload.create(
        storage_provider="oss",
        object_key="remake/sources/committed.mp4",
        original_filename="committed.mp4",
        status="committed",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    committed.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await expired.save(update_fields=["expires_at", "updated_at"])
    await committed.save(update_fields=["expires_at", "updated_at"])

    cleaned = await service.cleanup_expired()

    await expired.refresh_from_db()
    await committed.refresh_from_db()
    assert cleaned == 1
    assert expired.status == "expired"
    assert committed.status == "committed"
    assert provider.deleted == ["remake/sources/expired.mp4"]
