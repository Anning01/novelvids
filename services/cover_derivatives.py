"""项目封面派生图：保留原图，按使用场景生成轻量 WebP。

派生地址由原始封面引用确定，不增加数据库字段：

- ``thumbnail``：项目列表使用，最长边不超过 480px；
- ``preview``：项目详情页使用，最长边不超过 960px。

文件名包含原图 UUID，内容更新会自然得到新 URL，
可安全使用 immutable 缓存。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import cv2
import numpy as np


CoverDerivativeKind = Literal["thumbnail", "preview"]


@dataclass(frozen=True)
class CoverDerivativeSpec:
    max_width: int
    max_height: int
    quality: int


COVER_DERIVATIVE_SPECS: dict[CoverDerivativeKind, CoverDerivativeSpec] = {
    "thumbnail": CoverDerivativeSpec(max_width=320, max_height=480, quality=78),
    "preview": CoverDerivativeSpec(max_width=640, max_height=960, quality=82),
}


def cover_derivative_reference(
    cover: str | None,
    kind: CoverDerivativeKind,
) -> str | None:
    """返回封面的确定性派生引用；外部 URL 无法安全推导时返回 ``None``。"""
    if not cover or kind not in COVER_DERIVATIVE_SPECS:
        return None

    raw = cover.split("?", 1)[0]
    prefix = ""
    if raw.startswith("/media/"):
        prefix = "/media/"
        raw = raw[len(prefix) :]
    elif not raw.startswith(("uploads/", "remake/")):
        return None

    path = PurePosixPath(raw)
    if not path.name or path.suffix.lower() not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    }:
        return None
    derivative = path.parent / "derivatives" / f"{path.stem}-{kind}.webp"
    return f"{prefix}{derivative.as_posix()}"


def local_media_path(media_root: Path, media_reference: str | None) -> Path | None:
    """把本地 ``/media`` 引用转换为受限于媒体根目录的真实路径。"""
    if not media_reference or not media_reference.startswith("/media/"):
        return None
    root = media_root.resolve()
    path = (root / media_reference[len("/media/") :]).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def render_cover_derivatives(image_bytes: bytes) -> dict[CoverDerivativeKind, bytes]:
    """解码一次原图并输出两个 WebP 派生尺寸。"""
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        raise ValueError("封面图片无法解码")

    return {
        kind: _render_variant(image, spec)
        for kind, spec in COVER_DERIVATIVE_SPECS.items()
    }


def write_local_cover_derivatives(
    media_root: Path,
    cover_reference: str,
    image_bytes: bytes,
    *,
    force: bool = True,
) -> dict[CoverDerivativeKind, Path]:
    """以原子替换方式写入本地派生图。"""
    rendered = render_cover_derivatives(image_bytes)
    written: dict[CoverDerivativeKind, Path] = {}
    for kind, data in rendered.items():
        reference = cover_derivative_reference(cover_reference, kind)
        destination = local_media_path(media_root, reference)
        if destination is None:
            raise ValueError("封面不是受支持的本地媒体引用")
        if destination.exists() and not force:
            written[kind] = destination
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        written[kind] = destination
    return written


def _render_variant(image: np.ndarray, spec: CoverDerivativeSpec) -> bytes:
    height, width = image.shape[:2]
    scale = min(1.0, spec.max_width / width, spec.max_height / height)
    if scale < 1.0:
        target = (
            max(1, round(width * scale)),
            max(1, round(height * scale)),
        )
        image = cv2.resize(image, target, interpolation=cv2.INTER_AREA)

    success, output = cv2.imencode(
        ".webp",
        image,
        [cv2.IMWRITE_WEBP_QUALITY, spec.quality],
    )
    if not success:
        raise ValueError("封面 WebP 编码失败")
    return output.tobytes()
