"""对象存储入口：`oss` 为按配置构建的单例。"""
from services.oss.base import (
    LocalProvider,
    OSSProvider,
    make_upload_key,
    normalize_media_url,
    oss,
    resolve_media_url,
)

__all__ = [
    "LocalProvider",
    "OSSProvider",
    "make_upload_key",
    "normalize_media_url",
    "oss",
    "resolve_media_url",
]
