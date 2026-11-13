"""Resolve local video references through the application's object storage."""

from __future__ import annotations

import base64
import binascii
import mimetypes
from pathlib import Path

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from config import settings
from services.oss import make_upload_key, oss
from services.video.base import VideoProviderError
from utils.messages import localized_message


_HTTP_URL = TypeAdapter(AnyHttpUrl)


def public_media_url(value: str) -> str:
    try:
        parsed = _HTTP_URL.validate_python(value)
        if parsed.username or parsed.password:
            raise ValueError
    except (ValidationError, ValueError):
        raise VideoProviderError(localized_message('参考素材需要可访问的公网 HTTP(S) 地址')) from None
    return value


class PublicMediaResolver:
    """Upload local inputs once per request; never send Base64 to the video API."""

    def __init__(self, *, team_id: int | None, model_config=None):
        self.model_config = model_config
        self.team_id = team_id
        self._resolved: dict[str, str] = {}

    async def resolve(self, source: str) -> str:
        if source in self._resolved:
            return self._resolved[source]
        if not source.startswith(("data:", "/media/")):
            return public_media_url(source)
        from services.oss.studio_client import studio_client
        studio = studio_client(self.team_id, base_url=getattr(self.model_config, "base_url", None),
                              api_key=getattr(self.model_config, "api_key", None))
        if studio:
            # Check expiry and existence even if this resolver is retained between submissions.
            return await studio.resolve(source)
        if not oss.enabled:
            raise VideoProviderError(localized_message('当前视频接口需要公网参考素材，请配置对象存储或使用公网 URL'))
        if source.startswith("data:"):
            header, separator, encoded = source.partition(",")
            content_type = header[5:].split(";", 1)[0]
            if not separator or not header.endswith(";base64") or not content_type.startswith(("image/", "audio/", "video/")):
                raise VideoProviderError(localized_message('参考素材编码无效'))
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                raise VideoProviderError(localized_message('参考素材编码无效')) from None
            if not content:
                raise VideoProviderError(localized_message('参考素材内容为空'))
            suffix = mimetypes.guess_extension(content_type) or ".bin"
            key = make_upload_key(self.team_id, f"reference{suffix}")
            try:
                await oss.put_bytes(key, content, content_type)
            except Exception:
                raise VideoProviderError(localized_message('参考素材上传失败，请检查对象存储配置')) from None
        else:
            root = Path(settings.MEDIA_PATH).resolve()
            path = (root / source.removeprefix("/media/")).resolve()
            if root not in path.parents or not path.is_file():
                raise VideoProviderError(localized_message('本地参考素材不存在'))
            key = make_upload_key(self.team_id, path.name)
            try:
                await oss.put_file(key, path, mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            except Exception:
                raise VideoProviderError(localized_message('参考素材上传失败，请检查对象存储配置')) from None
        url = public_media_url(oss.public_url(key))
        self._resolved[source] = url
        return url
