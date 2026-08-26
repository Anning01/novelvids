"""Resolve persisted image references into provider-readable image inputs."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from config import settings
from services.oss import resolve_media_url


MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


def image_to_base64(image_path: str) -> str:
    """Convert one local image into a base64 data URI."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    mime_type = MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime_type};base64,{encoded}"


def resolve_image_source(raw: str) -> str:
    """Keep provider-readable URLs and convert local media into a data URI."""
    resolved = resolve_media_url(raw) or raw
    if resolved.startswith(("http://", "https://", "data:")):
        return resolved
    if resolved.startswith("/media/"):
        resolved = os.path.join(settings.MEDIA_PATH, resolved[len("/media/"):])
    return image_to_base64(resolved)


def resolve_reference_images(values: list[str]) -> list[str]:
    """Resolve and de-duplicate reference images while preserving their order."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(resolve_image_source(value))
    return result
