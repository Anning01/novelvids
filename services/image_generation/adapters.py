from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from utils.image_protocol import ImageApiProtocol


class ImageProtocolAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class ImageGenerationInput:
    model: str
    prompt: str
    resolution: str | None = None
    aspect_ratio: str | None = None
    count: int = 1
    extra_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreparedImageRequest:
    path: str
    payload: dict[str, Any]


class ImageProtocolAdapter(Protocol):
    def prepare(self, request: ImageGenerationInput) -> PreparedImageRequest: ...


def _openai_size(resolution: str | None, aspect_ratio: str | None) -> str | None:
    """Map resolution aliases to sizes accepted by OpenAI-compatible image APIs."""
    value = (resolution or "").strip()
    if value and "x" in value.lower():
        return value.lower()
    if not value:
        return None

    ratio = (aspect_ratio or "").strip()
    try:
        width, height = (float(part) for part in ratio.split(":", 1))
    except (TypeError, ValueError, ZeroDivisionError):
        width = height = 1
    if width > height:
        return "1536x1024"
    if height > width:
        return "1024x1536"
    return "1024x1024"


class OpenAICompatibleImageAdapter:
    def prepare(self, request: ImageGenerationInput) -> PreparedImageRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "n": max(1, min(4, int(request.count))),
            "response_format": "url",
        }
        size = _openai_size(request.resolution, request.aspect_ratio)
        if size:
            payload["size"] = size
        payload.update(request.extra_body or {})
        return PreparedImageRequest(path="/images/generations", payload=payload)


class OpenRouterCompatibleImageAdapter:
    """OpenRouter-style image endpoint with explicit resolution and aspect ratio."""

    def prepare(self, request: ImageGenerationInput) -> PreparedImageRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "n": max(1, min(10, int(request.count))),
            "output_format": "png",
        }
        if request.resolution:
            payload["resolution"] = request.resolution
        if request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        payload.update(request.extra_body or {})
        return PreparedImageRequest(path="/images", payload=payload)


class VolcengineArkImageAdapter:
    """Ark Seedream request shape, shared by Seedream model versions."""

    def prepare(self, request: ImageGenerationInput) -> PreparedImageRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "response_format": "url",
            "watermark": False,
            "sequential_image_generation": "disabled",
        }
        if request.resolution:
            payload["size"] = request.resolution
        payload.update(request.extra_body or {})
        return PreparedImageRequest(path="/images/generations", payload=payload)


_ADAPTERS: dict[ImageApiProtocol, ImageProtocolAdapter] = {
    ImageApiProtocol.openai_compatible: OpenAICompatibleImageAdapter(),
    ImageApiProtocol.openrouter_compatible: OpenRouterCompatibleImageAdapter(),
    ImageApiProtocol.volcengine_ark: VolcengineArkImageAdapter(),
}


def image_protocol_adapter(protocol: str) -> ImageProtocolAdapter:
    try:
        normalized = ImageApiProtocol(protocol)
        return _ADAPTERS[normalized]
    except (KeyError, ValueError) as exc:
        raise ImageProtocolAdapterError(f"不支持的生图接口协议: {protocol}") from exc
