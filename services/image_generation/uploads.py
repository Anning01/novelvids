"""Prepare reference-image files for multipart image APIs."""

from __future__ import annotations

import base64
import binascii

import httpx

from services.image_inputs import resolve_image_source


async def image_uploads(
    client: httpx.AsyncClient, references: tuple[str, ...],
) -> list[tuple[str, tuple[str, bytes, str]]]:
    files = []
    field = "image" if len(references) == 1 else "image[]"
    for index, reference in enumerate(references):
        source = resolve_image_source(reference)
        if source.startswith("data:"):
            header, separator, encoded = source.partition(",")
            if not separator or not header.endswith(";base64"):
                raise ValueError("参考图片必须是有效的 base64 图片")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("参考图片必须是有效的 base64 图片") from exc
        else:
            response = await client.get(source)
            response.raise_for_status()
            content = response.content

        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            extension, mime = "png", "image/png"
        elif content.startswith(b"\xff\xd8\xff"):
            extension, mime = "jpg", "image/jpeg"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            extension, mime = "webp", "image/webp"
        else:
            raise ValueError("参考图片仅支持 PNG、JPEG 或 WebP")
        files.append((field, (f"reference-{index + 1}.{extension}", content, mime)))
    return files
