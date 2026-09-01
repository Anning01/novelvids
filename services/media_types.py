"""注册精简运行镜像中可能缺失的媒体 MIME 类型。"""

from __future__ import annotations

import mimetypes


def register_media_mime_types() -> None:
    """确保浏览器可在 ``nosniff`` 策略下正确识别衍生媒体。"""

    mimetypes.add_type("image/webp", ".webp", strict=True)
