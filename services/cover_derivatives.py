"""图片派生图：保留原图，按使用场景生成轻量 WebP。

派生地址由原始封面引用确定，不增加数据库字段：

- ``thumbnail``：项目列表使用，最长边不超过 480px；
- ``preview``：项目详情页使用，最长边不超过 960px。

文件名包含原图 UUID，内容更新会自然得到新 URL，
可安全使用 immutable 缓存。
"""

from __future__ import annotations

from utils.messages import localized_message

from pathlib import Path, PurePosixPath
from typing import Literal

from services.media_images import CoverDerivativeSpec, COVER_DERIVATIVE_SPECS

CoverDerivativeKind = Literal["thumbnail", "preview"]
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"

def image_derivative_reference(
    cover: str | None,
    kind: CoverDerivativeKind,
) -> str | None:
    """返回受管图片的确定性派生引用；外部 URL 无法安全推导时返回 ``None``。"""
    if not cover or kind not in COVER_DERIVATIVE_SPECS:
        return None

    raw = cover.split("?", 1)[0]
    prefix = ""
    if raw.startswith("/media/"):
        prefix = "/media/"
        raw = raw[len(prefix) :]
    elif raw.startswith(("./media/", "media/")):
        prefix = "/media/"
        raw = raw.split("media/", 1)[1]
    elif not raw.startswith(("uploads/", "remake/")):
        return None

    path = PurePosixPath(raw)
    if not path.name or path.suffix.lower() not in {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
    }:
        return None
    derivative = path.parent / "derivatives" / f"{path.stem}-{kind}.webp"
    return f"{prefix}{derivative.as_posix()}"


def cover_derivative_reference(
    cover: str | None,
    kind: CoverDerivativeKind,
) -> str | None:
    """兼容既有封面调用；封面和设定资产共享同一派生规则。"""
    return image_derivative_reference(cover, kind)


def local_media_path(media_root: Path, media_reference: str | None) -> Path | None:
    """把本地 ``/media`` 引用转换为受限于媒体根目录的真实路径。"""
    if not media_reference:
        return None
    raw = media_reference
    if raw.startswith("/media/"):
        raw = raw[len("/media/") :]
    elif raw.startswith(("./media/", "media/")):
        raw = raw.split("media/", 1)[1]
    else:
        return None
    root = media_root.resolve()
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def render_cover_derivatives(image_bytes: bytes) -> dict[CoverDerivativeKind, bytes]:
    from services.media_processing import image_derivatives
    return image_derivatives(image_bytes)


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
        reference = image_derivative_reference(cover_reference, kind)
        destination = local_media_path(media_root, reference)
        if destination is None:
            raise ValueError(localized_message('封面不是受支持的本地媒体引用'))
        if destination.exists() and not force:
            written[kind] = destination
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(destination)
        written[kind] = destination
    return written


async def ensure_image_derivatives(
    image_reference: str,
    image_bytes: bytes | None = None,
    *,
    force: bool = False,
) -> dict[CoverDerivativeKind, str]:
    """为本地或 OSS 图片补齐派生图，返回仍可落库的稳定引用。

    外部图片不会由服务端下载，避免把通用派生能力变成 SSRF 入口。
    """
    import asyncio

    from config import settings
    from services.oss import normalize_media_url, oss

    stored = normalize_media_url(image_reference) or image_reference
    references = {
        kind: image_derivative_reference(stored, kind)
        for kind in COVER_DERIVATIVE_SPECS
    }
    if not all(references.values()):
        return {}

    media_root = Path(settings.MEDIA_PATH)
    if stored.startswith(("/media/", "./media/", "media/")):
        destinations = {
            kind: local_media_path(media_root, reference)
            for kind, reference in references.items()
        }
        if not force and all(path and path.is_file() for path in destinations.values()):
            return {kind: str(reference) for kind, reference in references.items()}
        source = local_media_path(media_root, stored)
        if image_bytes is None:
            if source is None or not source.is_file():
                raise FileNotFoundError("本地图片不存在")
            image_bytes = await asyncio.to_thread(source.read_bytes)
        await asyncio.to_thread(
            write_local_cover_derivatives,
            media_root,
            stored,
            image_bytes,
            force=force,
        )
        return {kind: str(reference) for kind, reference in references.items()}

    if oss.enabled and stored.startswith(("uploads/", "remake/")):
        if image_bytes is None:
            image_bytes = await oss.get_bytes(stored)
        derivatives = await asyncio.to_thread(render_cover_derivatives, image_bytes)
        for kind, data in derivatives.items():
            reference = references[kind]
            if reference:
                await oss.put_bytes(
                    reference,
                    data,
                    "image/webp",
                    cache_control=IMMUTABLE_CACHE_CONTROL,
                )
        return {kind: str(reference) for kind, reference in references.items()}
    return {}
