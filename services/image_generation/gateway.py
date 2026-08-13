from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.image_generation.adapters import (
    ImageGenerationInput,
    image_protocol_adapter,
)
from utils.image_protocol import ImageApiProtocol

logger = logging.getLogger(__name__)


class ImageGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeneratedImage:
    url: str | None = None
    b64_json: str | None = None


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _safe_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    if parsed.port is not None:
        hostname = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def _request_id(response: httpx.Response) -> str | None:
    for name in ("x-request-id", "request-id", "x-volc-request-id"):
        value = response.headers.get(name)
        if value:
            return value
    return None


def _payload_error(payload: Any) -> tuple[str | None, int | None, str | None]:
    """Return sanitized details from providers that wrap errors in HTTP 200."""
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return None, None, None
    error = payload["error"]
    metadata = error.get("metadata") if isinstance(error.get("metadata"), dict) else {}
    raw_code = metadata.get("router_code") or error.get("code") or metadata.get("error_type")
    raw_status = metadata.get("original_status_code")
    raw_request_id = metadata.get("request_id")
    code = str(raw_code)[:80] if raw_code is not None else "PROVIDER_ERROR"
    status = raw_status if isinstance(raw_status, int) else None
    request_id = str(raw_request_id)[:120] if raw_request_id else None
    return code, status, request_id


def _parse_images(payload: Any) -> list[GeneratedImage]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        raw_items = payload.get("images")
    if not isinstance(raw_items, list):
        return []

    images: list[GeneratedImage] = []
    for item in raw_items:
        if isinstance(item, str) and item.strip():
            images.append(GeneratedImage(url=item.strip()))
            continue
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        b64_json = item.get("b64_json") or item.get("base64")
        if isinstance(url, str) and url.strip():
            images.append(GeneratedImage(url=url.strip()))
        elif isinstance(b64_json, str) and b64_json.strip():
            images.append(GeneratedImage(b64_json=b64_json.strip()))
    return images


async def generate_images(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    api_protocol: str = ImageApiProtocol.openai_compatible.value,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
    count: int = 1,
    output_format: str = "png",
    quality: str | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float = 300,
) -> list[GeneratedImage]:
    """Generate images through a backend-configured provider protocol."""
    prepared = image_protocol_adapter(api_protocol).prepare(
        ImageGenerationInput(
            model=model,
            prompt=prompt,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            count=count,
            output_format=output_format,
            quality=quality,
            extra_body=extra_body,
        )
    )
    endpoint = _endpoint(base_url, prepared.path)
    safe_endpoint = _safe_endpoint(endpoint)
    logger.info(
        "image_generation_outbound protocol=%s endpoint=%s model=%s size=%s count=%s",
        api_protocol,
        safe_endpoint,
        model,
        prepared.payload.get("size"),
        count,
    )

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=prepared.payload,
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "image_generation_network_error protocol=%s endpoint=%s error_type=%s",
            api_protocol,
            safe_endpoint,
            type(exc).__name__,
        )
        raise ImageGenerationError("生图供应商网络请求失败") from exc

    request_id = _request_id(response)
    if response.status_code >= 400:
        logger.warning(
            "image_generation_http_error protocol=%s endpoint=%s status=%s request_id=%s",
            api_protocol,
            safe_endpoint,
            response.status_code,
            request_id or "-",
        )
        suffix = f"，request_id={request_id}" if request_id else ""
        raise ImageGenerationError(
            f"生图供应商请求失败（HTTP {response.status_code}{suffix}）"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning(
            "image_generation_invalid_json protocol=%s endpoint=%s status=%s request_id=%s",
            api_protocol,
            safe_endpoint,
            response.status_code,
            request_id or "-",
        )
        raise ImageGenerationError("生图供应商返回了无法解析的响应") from exc

    error_code, original_status, payload_request_id = _payload_error(payload)
    request_id = request_id or payload_request_id
    if error_code:
        logger.warning(
            "image_generation_provider_error protocol=%s endpoint=%s status=%s "
            "original_status=%s request_id=%s code=%s",
            api_protocol,
            safe_endpoint,
            response.status_code,
            original_status or "-",
            request_id or "-",
            error_code,
        )
        status_suffix = f"，上游 HTTP {original_status}" if original_status else ""
        request_suffix = f"，request_id={request_id}" if request_id else ""
        raise ImageGenerationError(
            f"生图供应商返回错误（{error_code}{status_suffix}{request_suffix}）"
        )

    images = _parse_images(payload)
    keys = sorted(payload.keys()) if isinstance(payload, dict) else []
    logger.info(
        "image_generation_inbound protocol=%s endpoint=%s status=%s request_id=%s keys=%s image_count=%s",
        api_protocol,
        safe_endpoint,
        response.status_code,
        request_id or "-",
        keys,
        len(images),
    )
    if not images:
        suffix = f"（request_id={request_id}）" if request_id else ""
        raise ImageGenerationError(f"生图供应商未返回图片{suffix}")
    return images
