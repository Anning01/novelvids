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
    output_format: str = "png"
    quality: str | None = None
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
        }
        size = _openai_size(request.resolution, request.aspect_ratio)
        if size:
            payload["size"] = size
        payload["output_format"] = request.output_format
        if request.quality:
            payload["quality"] = request.quality
        payload.update(request.extra_body or {})
        return PreparedImageRequest(path="/images/generations", payload=payload)


class OpenRouterCompatibleImageAdapter:
    """OpenRouter-style image endpoint with mutually exclusive size controls."""

    def prepare(self, request: ImageGenerationInput) -> PreparedImageRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "n": max(1, min(10, int(request.count))),
            "output_format": request.output_format,
        }
        resolution = (request.resolution or "").strip()
        has_explicit_size = "x" in resolution.lower()
        if has_explicit_size:
            payload["size"] = resolution.lower()
        elif resolution:
            payload["resolution"] = resolution
        if request.aspect_ratio and not has_explicit_size:
            payload["aspect_ratio"] = request.aspect_ratio
        payload.update(request.extra_body or {})
        return PreparedImageRequest(path="/images", payload=payload)


class VolcengineArkImageAdapter:
    """Ark Seedream request shape.

    ``sequential_image_generation`` 仅 Seedream 3.0 支持；4.0/5.0 已移除该参数，
    无条件传入会被 Ark 以 InvalidParameter（HTTP 400）拒绝。
    """

    def prepare(self, request: ImageGenerationInput) -> PreparedImageRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "prompt": request.prompt,
            "response_format": "url",
            "watermark": False,
        }
        if "seedream-3" in request.model.lower():
            payload["sequential_image_generation"] = "disabled"
        if request.resolution:
            payload["size"] = request.resolution
        payload["output_format"] = request.output_format
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
