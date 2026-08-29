from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile

from config import settings
from exceptions.remake import RemakeError
from models.remake_upload import RemakeUpload
from services.oss import oss
from services.remake.media import MAX_REMAKE_BYTES, RemakeMediaValidator, ValidatedRemakeMedia

logger = logging.getLogger(__name__)


class RemakeUploadService:
    """本地/OSS 暂存、所有权、终局校验、释放和提交前物化。"""

    def __init__(
        self,
        *,
        validator=None,
        provider=None,
        media_root: Path | str | None = None,
        max_bytes: int = MAX_REMAKE_BYTES,
    ) -> None:
        self.validator = validator or RemakeMediaValidator()
        self.provider = provider or oss
        self.media_root = Path(media_root or settings.MEDIA_PATH).resolve()
        self.max_bytes = max_bytes

    def _path(self, object_key: str) -> Path:
        path = (self.media_root / object_key).resolve()
        if path != self.media_root and self.media_root not in path.parents:
            raise RemakeError(404, "REMAKE_UPLOAD_NOT_FOUND", "暂存视频不存在")
        return path

    @staticmethod
    def _safe_name(filename: str) -> str:
        name = Path(filename or "video.mp4").name
        return re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]", "_", name)[:120] or "video.mp4"

    async def stage_local(
        self,
        file: UploadFile,
        *,
        team_id: int | None,
        user_id: int | None,
    ) -> RemakeUpload:
        if self.provider.enabled:
            raise RemakeError(
                409,
                "REMAKE_UPLOAD_DIRECT_REQUIRED",
                "当前环境需要浏览器直传对象存储",
                retryable=True,
            )
        original_filename = self._safe_name(file.filename or "video.mp4")
        self.validator.validate_extension(original_filename)
        token = uuid4()
        extension = Path(original_filename).suffix.lower()
        object_key = f"remake/.staging/{token}{extension}"
        upload = await RemakeUpload.create(
            id=token,
            storage_provider="local",
            object_key=object_key,
            original_filename=original_filename,
            mime_type=file.content_type or None,
            team_id=team_id,
            created_by=user_id,
        )
        destination = self._path(object_key)
        temporary = destination.with_suffix(destination.suffix + ".uploading")
        destination.parent.mkdir(parents=True, exist_ok=True)
        size_bytes = 0
        try:
            with temporary.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size_bytes += len(chunk)
                    if size_bytes > self.max_bytes:
                        raise RemakeError(
                            413,
                            "REMAKE_MEDIA_SIZE_EXCEEDED",
                            "单个来源视频不能超过500MB",
                            context={"filename": original_filename, "limit_bytes": self.max_bytes},
                        )
                    await asyncio.to_thread(target.write, chunk)
            os.replace(temporary, destination)
            upload.status = "validating"
            upload.size_bytes = size_bytes
            await upload.save(update_fields=["status", "size_bytes", "updated_at"])
            media = await asyncio.to_thread(
                self.validator.validate_path,
                destination,
                original_filename=original_filename,
                mime_type=file.content_type or None,
            )
            await self._mark_ready(upload, media)
            return upload
        except Exception as error:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            upload.status = "failed"
            if isinstance(error, RemakeError):
                upload.error_code = error.error_code
                upload.error_message = error.message
            else:
                upload.error_code = "REMAKE_MEDIA_INVALID_CONTAINER"
                upload.error_message = "来源视频上传失败"
            await upload.save(
                update_fields=["status", "error_code", "error_message", "updated_at"]
            )
            raise
        finally:
            await file.close()

    async def create_policy(
        self,
        *,
        filename: str,
        content_type: str,
        size_bytes: int,
        team_id: int | None,
        user_id: int | None,
    ) -> tuple[RemakeUpload, dict]:
        if not self.provider.enabled:
            raise RemakeError(409, "REMAKE_UPLOAD_NOT_READY", "当前环境使用本地上传")
        original_filename = self._safe_name(filename)
        self.validator.validate_extension(original_filename)
        if size_bytes <= 0 or size_bytes > self.max_bytes:
            raise RemakeError(
                413,
                "REMAKE_MEDIA_SIZE_EXCEEDED",
                "单个来源视频不能超过500MB",
                context={"filename": original_filename, "limit_bytes": self.max_bytes},
            )
        token = uuid4()
        key = (
            f"remake/sources/{team_id or 0}/{user_id or 0}/"
            f"{token}-{original_filename}"
        )
        upload = await RemakeUpload.create(
            id=token,
            storage_provider=self.provider.name,
            object_key=key,
            original_filename=original_filename,
            mime_type=content_type or None,
            size_bytes=size_bytes,
            team_id=team_id,
            created_by=user_id,
        )
        return upload, self.provider.sign_form_upload(key, content_type, self.max_bytes)

    async def finalize_oss(
        self,
        *,
        object_key: str,
        original_filename: str,
        team_id: int | None,
        user_id: int | None,
    ) -> RemakeUpload:
        upload = await self._owned_by_key(object_key, team_id=team_id, user_id=user_id)
        if upload.status == "ready":
            return upload
        if upload.status != "uploading" or upload.original_filename != self._safe_name(original_filename):
            raise RemakeError(409, "REMAKE_UPLOAD_NOT_READY", "暂存视频状态无效")
        upload.status = "validating"
        await upload.save(update_fields=["status", "updated_at"])
        validate_dir = self.media_root / "remake" / ".validate"
        validate_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f"{upload.id}-",
            suffix=Path(upload.original_filename).suffix.lower(),
            dir=validate_dir,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            await self.provider.download_to_file(upload.object_key, temporary)
            media = await asyncio.to_thread(
                self.validator.validate_path,
                temporary,
                original_filename=upload.original_filename,
                mime_type=upload.mime_type,
            )
            await self._mark_ready(upload, media)
            return upload
        except Exception as error:
            upload.status = "failed"
            if isinstance(error, RemakeError):
                upload.error_code = error.error_code
                upload.error_message = error.message
            else:
                upload.error_code = "REMAKE_MEDIA_INVALID_CONTAINER"
                upload.error_message = "对象存储视频校验失败"
            await upload.save(
                update_fields=["status", "error_code", "error_message", "updated_at"]
            )
            raise
        finally:
            temporary.unlink(missing_ok=True)

    async def _mark_ready(
        self,
        upload: RemakeUpload,
        media: ValidatedRemakeMedia,
    ) -> None:
        upload.status = "ready"
        upload.size_bytes = media.size_bytes
        upload.duration_seconds = media.duration_seconds
        upload.width = media.width
        upload.height = media.height
        upload.container_format = media.container_format
        upload.checksum = media.checksum
        upload.error_code = None
        upload.error_message = None
        await upload.save(
            update_fields=[
                "status",
                "size_bytes",
                "duration_seconds",
                "width",
                "height",
                "container_format",
                "checksum",
                "error_code",
                "error_message",
                "updated_at",
            ]
        )

    async def _owned_by_key(
        self,
        object_key: str,
        *,
        team_id: int | None,
        user_id: int | None,
    ) -> RemakeUpload:
        upload = await RemakeUpload.get_or_none(
            object_key=object_key,
            team_id=team_id,
            created_by=user_id,
        )
        if upload is None:
            raise RemakeError(404, "REMAKE_UPLOAD_NOT_FOUND", "暂存视频不存在")
        return upload

    async def get_ready(
        self,
        upload_id: UUID,
        *,
        team_id: int | None,
        user_id: int | None,
    ) -> RemakeUpload:
        upload = await RemakeUpload.get_or_none(
            id=upload_id,
            team_id=team_id,
            created_by=user_id,
        )
        if upload is None:
            raise RemakeError(404, "REMAKE_UPLOAD_NOT_FOUND", "暂存视频不存在")
        now = datetime.now(timezone.utc)
        if upload.expires_at <= now and upload.status != "committed":
            await self._expire(upload)
            raise RemakeError(410, "REMAKE_UPLOAD_EXPIRED", "暂存视频已过期，请重新上传")
        if upload.status == "committed":
            raise RemakeError(409, "REMAKE_UPLOAD_ALREADY_COMMITTED", "暂存视频已经绑定项目")
        if upload.status != "ready":
            raise RemakeError(
                409,
                "REMAKE_UPLOAD_NOT_READY",
                "暂存视频尚未完成校验",
                retryable=upload.status in {"uploading", "validating"},
            )
        return upload

    async def revalidate(self, upload: RemakeUpload) -> ValidatedRemakeMedia:
        if upload.storage_provider == "local":
            path = self._path(upload.object_key)
            if not path.is_file():
                raise RemakeError(404, "REMAKE_UPLOAD_NOT_FOUND", "暂存视频不存在")
            media = await asyncio.to_thread(
                self.validator.validate_path,
                path,
                original_filename=upload.original_filename,
                mime_type=upload.mime_type,
            )
        else:
            validate_dir = self.media_root / "remake" / ".validate"
            validate_dir.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(
                prefix=f"commit-{upload.id}-",
                suffix=Path(upload.original_filename).suffix.lower(),
                dir=validate_dir,
            )
            os.close(fd)
            temporary = Path(name)
            try:
                await self.provider.download_to_file(upload.object_key, temporary)
                media = await asyncio.to_thread(
                    self.validator.validate_path,
                    temporary,
                    original_filename=upload.original_filename,
                    mime_type=upload.mime_type,
                )
            finally:
                temporary.unlink(missing_ok=True)
        if media.checksum != upload.checksum or media.size_bytes != upload.size_bytes:
            raise RemakeError(409, "REMAKE_UPLOAD_NOT_READY", "暂存视频内容已经变化")
        return media

    async def promote_local(self, upload: RemakeUpload) -> tuple[str, str] | None:
        if upload.storage_provider != "local":
            return None
        old_key = upload.object_key
        extension = Path(upload.original_filename).suffix.lower()
        new_key = f"remake/sources/{upload.id}{extension}"
        source = self._path(old_key)
        destination = self._path(new_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(os.replace, source, destination)
        return old_key, new_key

    async def rollback_promotion(self, promotion: tuple[str, str] | None) -> None:
        if promotion is None:
            return
        old_key, new_key = promotion
        source = self._path(new_key)
        destination = self._path(old_key)
        if not source.exists():
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(os.replace, source, destination)

    async def release(
        self,
        upload_id: UUID,
        *,
        team_id: int | None,
        user_id: int | None,
    ) -> None:
        upload = await RemakeUpload.get_or_none(
            id=upload_id,
            team_id=team_id,
            created_by=user_id,
        )
        if upload is None:
            raise RemakeError(404, "REMAKE_UPLOAD_NOT_FOUND", "暂存视频不存在")
        if upload.status == "committed":
            raise RemakeError(409, "REMAKE_UPLOAD_ALREADY_COMMITTED", "暂存视频已经绑定项目")
        await self._delete_media(upload)
        await upload.delete()

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        """清理过期未提交对象；保留 expired 记录用于稳定的 token 错误语义。"""
        threshold = now or datetime.now(timezone.utc)
        uploads = await RemakeUpload.filter(expires_at__lte=threshold).exclude(
            status__in=["committed", "expired"]
        )
        cleaned = 0
        for upload in uploads:
            try:
                await self._expire(upload)
                cleaned += 1
            except Exception:
                logger.exception("Failed to cleanup expired remake upload: %s", upload.id)
        return cleaned

    async def _expire(self, upload: RemakeUpload) -> None:
        if upload.status == "expired":
            return
        await self._delete_media(upload)
        upload.status = "expired"
        await upload.save(update_fields=["status", "updated_at"])

    async def _delete_media(self, upload: RemakeUpload) -> None:
        if upload.storage_provider == "local":
            self._path(upload.object_key).unlink(missing_ok=True)
        elif hasattr(self.provider, "delete"):
            await self.provider.delete(upload.object_key)


remake_upload_service = RemakeUploadService()
