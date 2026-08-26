"""Upload local model inputs to DashScope's model-bound temporary storage."""

from __future__ import annotations

import base64
import binascii
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from config import settings
from services.video.base import VideoProviderError


_UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
_DATA_URI_SUFFIXES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


class DashScopeTemporaryUploadError(VideoProviderError):
    """Sanitized temporary-storage failure safe for persistence and UI display."""


@dataclass(frozen=True)
class _UploadSource:
    filename: str
    content_type: str
    size_bytes: int
    content: bytes | Path


def _safe_local_media_path(source: str) -> Path:
    media_root = Path(settings.MEDIA_PATH).resolve()
    relative = source.removeprefix("/media/")
    path = (media_root / relative).resolve()
    if media_root not in path.parents or not path.is_file():
        raise DashScopeTemporaryUploadError("Wan 3 本地参考素材不存在")
    return path


def _data_uri_source(source: str) -> _UploadSource:
    header, separator, encoded = source.partition(",")
    if not separator or not header.startswith("data:") or ";base64" not in header.lower():
        raise DashScopeTemporaryUploadError("Wan 3 本地参考素材编码无效")
    content_type = header[5:].split(";", 1)[0].lower()
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DashScopeTemporaryUploadError("Wan 3 本地参考素材 Base64 无效") from exc
    if not content:
        raise DashScopeTemporaryUploadError("Wan 3 本地参考素材内容为空")
    suffix = _DATA_URI_SUFFIXES.get(content_type) or mimetypes.guess_extension(content_type) or ".bin"
    return _UploadSource(
        filename=f"{uuid4().hex}{suffix}",
        content_type=content_type or "application/octet-stream",
        size_bytes=len(content),
        content=content,
    )


def _local_file_source(source: str) -> _UploadSource:
    path = _safe_local_media_path(source)
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return _UploadSource(
        filename=f"{uuid4().hex}{path.suffix.lower()}",
        content_type=content_type,
        size_bytes=path.stat().st_size,
        content=path,
    )


def _upload_source(source: str) -> _UploadSource | None:
    if source.startswith("data:"):
        return _data_uri_source(source)
    if source.startswith("/media/"):
        return _local_file_source(source)
    return None


def _policy_field(data: dict[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, (str, int, float)) or not str(value).strip():
        raise DashScopeTemporaryUploadError("阿里云百炼未返回完整的临时上传凭证")
    return str(value).strip()


def _validated_upload_host(value: str) -> str:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com")
    ):
        raise DashScopeTemporaryUploadError("阿里云百炼返回了无效的临时上传地址")
    return value.rstrip("/")


class DashScopeTemporaryFileUploader:
    """Resolve local inputs to 48-hour ``oss://`` URLs bound to one model."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self._resolved: dict[str, str] = {}

    async def resolve(self, source: str) -> str:
        normalized = source.strip()
        upload = _upload_source(normalized)
        if upload is None:
            return normalized
        if cached := self._resolved.get(normalized):
            return cached
        resolved = await self._upload(upload)
        self._resolved[normalized] = resolved
        return resolved

    async def _upload(self, source: _UploadSource) -> str:
        if source.size_bytes > _MAX_UPLOAD_BYTES:
            raise DashScopeTemporaryUploadError("Wan 3 本地参考素材不能超过 1GB")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(120, connect=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                policy_response = await client.get(
                    _UPLOAD_POLICY_URL,
                    headers=headers,
                    params={"action": "getPolicy", "model": self.model},
                )
            except httpx.HTTPError as exc:
                raise DashScopeTemporaryUploadError("获取阿里云百炼临时上传凭证失败") from exc
            if policy_response.status_code >= 400:
                raise DashScopeTemporaryUploadError(
                    f"获取阿里云百炼临时上传凭证失败（HTTP {policy_response.status_code}）"
                )
            try:
                payload = policy_response.json()
            except ValueError as exc:
                raise DashScopeTemporaryUploadError("阿里云百炼临时上传凭证响应无法解析") from exc
            policy = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(policy, dict):
                raise DashScopeTemporaryUploadError("阿里云百炼未返回临时上传凭证")

            try:
                max_size_mb = float(_policy_field(policy, "max_file_size_mb"))
            except ValueError as exc:
                raise DashScopeTemporaryUploadError("阿里云百炼返回了无效的临时上传大小限制") from exc
            if max_size_mb <= 0:
                raise DashScopeTemporaryUploadError("阿里云百炼返回了无效的临时上传大小限制")
            if source.size_bytes > max_size_mb * 1024 * 1024:
                raise DashScopeTemporaryUploadError(
                    f"Wan 3 本地参考素材超过临时存储允许的 {max_size_mb:g}MB"
                )
            upload_host = _validated_upload_host(_policy_field(policy, "upload_host"))
            key = f"{_policy_field(policy, 'upload_dir').rstrip('/')}/{source.filename}"
            form = {
                "OSSAccessKeyId": _policy_field(policy, "oss_access_key_id"),
                "Signature": _policy_field(policy, "signature"),
                "policy": _policy_field(policy, "policy"),
                "x-oss-object-acl": _policy_field(policy, "x_oss_object_acl"),
                "x-oss-forbid-overwrite": _policy_field(policy, "x_oss_forbid_overwrite"),
                "key": key,
                "success_action_status": "200",
            }
            try:
                if isinstance(source.content, Path):
                    with source.content.open("rb") as content:
                        upload_response = await client.post(
                            upload_host,
                            data=form,
                            files={"file": (source.filename, content, source.content_type)},
                        )
                else:
                    upload_response = await client.post(
                        upload_host,
                        data=form,
                        files={"file": (source.filename, source.content, source.content_type)},
                    )
            except httpx.HTTPError as exc:
                raise DashScopeTemporaryUploadError("上传 Wan 3 本地参考素材失败") from exc
            if upload_response.status_code != 200:
                raise DashScopeTemporaryUploadError(
                    f"上传 Wan 3 本地参考素材失败（HTTP {upload_response.status_code}）"
                )
        return f"oss://{key}"
