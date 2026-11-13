"""URL-only image generation; media bytes travel between clients, storage and suppliers."""
import asyncio
import json
from ipaddress import ip_address
from math import gcd, isfinite
import time
from typing import Literal

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator

from auth.models import PlatformCallReceipt
from services.image_generation.adapters import ImageGenerationInput, image_protocol_adapter
from services.image_generation.capabilities import capabilities_for, validate_protocol, validate_selection
from services.platform.calls import CALL_TIMEOUT, admit, record_measurement
from services.platform.http_contract import UpstreamResponseError


def media_url(value):
    url = TypeAdapter(HttpUrl).validate_python(value)
    if url.scheme != "https" or url.username or url.password or not url.host or "." not in url.host or url.host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("需要可读取的公网 HTTPS 图片地址")
    try:
        ip = ip_address(url.host.strip("[]"))
    except ValueError:
        pass
    else:
        if not ip.is_global:
            raise ValueError("需要可读取的公网 HTTPS 图片地址")
    return str(url)


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)
    size: str | None = Field(None, max_length=32)
    aspect_ratio: str | None = Field(None, max_length=16)
    n: int = Field(1, gt=0)
    output_format: str = Field("png", max_length=10)
    image: list[str] = Field(default_factory=list)
    frame_count: int | None = None
    frame_duration_ms: int | None = None
    response_format: Literal["url"] = "url"
    quality: str | None = None
    background: str | None = None
    moderation: str | None = None
    output_compression: int | None = Field(None, ge=0, le=100)
    style: str | None = None
    user: str | None = None
    stream: bool = False
    partial_images: int | None = Field(None, ge=0, le=3)

    @field_validator("image")
    @classmethod
    def public_references(cls, values):
        return [media_url(v) for v in values]


def selection(config, body):
    caps = capabilities_for(config.image_model_type)
    size = body.get("size")
    if size == "auto":
        size = None
    ratio = body.get("aspect_ratio")
    if size and "x" in size:
        match = next(((tier, caps.aspect_ratios[sizes.index(size)]) for tier, sizes in caps.sizes.items() if size in sizes), None)
        if not match and config.api_protocol == "openai_compatible":
            try:
                width, height = (int(value) for value in size.split("x"))
                divisor = gcd(width, height)
                native_ratio = f"{width // divisor}:{height // divisor}"
                tier = next(tier for tier, sizes in caps.sizes.items()
                            if min(width, height) == int(sizes[0].split("x")[0]))
                if native_ratio in caps.aspect_ratios:
                    match = tier, native_ratio
            except (ValueError, StopIteration, ZeroDivisionError):
                pass
        if not match or ratio and ratio != match[1]:
            raise HTTPException(422, "尺寸与所选模型画幅不匹配")
        size, ratio = match
    return validate_selection(config.image_model_type, clarity=size, aspect_ratio=ratio,
        output_format=body["output_format"], generation_count=body["n"], frame_count=body.get("frame_count"),
        frame_duration_ms=body.get("frame_duration_ms"))


def image_options(config, body):
    if 2 not in (config.task_types or [config.task_type]):
        raise HTTPException(422, "所选模型不支持图像生成")
    if config.api_protocol == "novelvids":
        raise HTTPException(422, "平台模型需要配置上游供应商")
    validate_protocol(config.image_model_type, config.api_protocol)
    if body.get("image") and config.api_protocol == "openai_compatible":
        raise HTTPException(422, "该供应商的编辑协议需要文件上传，请选择支持 URL 参考图的模型配置")
    if body.get("stream"):
        raise HTTPException(400, "Image results must use URLs; image binary streams are not supported")
    selected = selection(config, body)
    pricing = config.pricing or {}
    price = (pricing.get("prices") or {}).get(selected.clarity)
    if pricing.get("type") != "image" or type(price) not in (float, int) or not isfinite(price) or price < 0:
        raise HTTPException(422, "所选清晰度尚未配置图片价格")
    return pricing


async def generate(ctx, request, key):
    body = request.model_dump(exclude_none=True)
    config, receipt = await admit(ctx, request.model, body, key, validate=image_options, kind="image")
    headers = {"X-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    selected = selection(config, body)
    extra = {"image": request.image} if request.image else {}
    if selected.output_format == "gif":
        extra.update(frame_count=selected.frame_count, frame_duration_ms=selected.frame_duration_ms)
    prepared = image_protocol_adapter(config.api_protocol).prepare(ImageGenerationInput(
        model=config.model, prompt=request.prompt, resolution=selected.provider_size, aspect_ratio=selected.aspect_ratio,
        count=request.n, output_format=selected.output_format, quality=request.quality or selected.provider_quality, extra_body=extra))
    payload = dict(prepared.payload)
    payload["response_format"] = "url"
    if config.api_protocol == "openai_compatible":
        if request.size and ("x" in request.size or request.size == "auto"):
            payload["size"] = request.size
        if request.quality is None:
            payload.pop("quality", None)
        if "output_format" not in request.model_fields_set:
            payload.pop("output_format", None)
    for field in ("background", "moderation", "output_compression", "style", "user"):
        if field in body:
            payload[field] = body[field]
    if request.partial_images is not None:
        payload["partial_images"] = request.partial_images
    payload.update(request.model_extra or {})
    upstream_path = prepared.path
    upstream_body = {"json":payload}
    provider_id = None
    client, upstream = None, None
    input_count = len(request.image)
    deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT
    try:
        client = httpx.AsyncClient(timeout=CALL_TIMEOUT, follow_redirects=False)
        async with asyncio.timeout_at(deadline):
            upstream = await client.send(client.build_request("POST", config.base_url.rstrip("/") + upstream_path,
                headers={"Authorization":"Bearer "+config.api_key}, **upstream_body), stream=True)
            provider_id = upstream.headers.get("x-request-id")
            max_bytes = 1024 * 1024
            length = upstream.headers.get("content-length")
            if length and int(length) > max_bytes:
                raise ValueError("Image response exceeds limit")
            payload = bytearray()
            async for chunk in upstream.aiter_bytes(chunk_size=16*1024):
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise ValueError("Image response exceeds limit")
        if upstream.status_code >= 400:
            state = "rejected" if upstream.status_code < 500 and upstream.status_code != 408 else "review"
            await PlatformCallReceipt.filter(id=receipt.id).update(state=state, provider_id=provider_id)
            raise UpstreamResponseError(httpx.Response(upstream.status_code, content=bytes(payload), headers=upstream.headers),
                str(receipt.public_id), config.api_key)
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("Missing image result")
        if raw.get("error"):
            await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected", provider_id=provider_id)
            raise UpstreamResponseError(httpx.Response(200, content=bytes(payload), headers=upstream.headers), str(receipt.public_id), config.api_key)
        items = raw.get("data", raw.get("images", []))
        for item in items:
            if isinstance(item, dict) and item.get("b64_json"):
                raise ValueError("Provider returned inline media instead of the requested URL")
            media_url(item.get("url") if isinstance(item, dict) else item)
        if not items or len(items) > request.n:
            raise ValueError("Unconfirmed image count")
        await record_measurement(receipt, {"image_count":len(items),"clarity":selected.clarity,"input_image_count":input_count},provider_id)
        result = raw if "data" in raw else {"created":int(time.time()),"data":[{"url":item} if isinstance(item, str) else item for item in items]}
        return JSONResponse(result, headers=headers)
    except (HTTPException, UpstreamResponseError):
        raise
    except Exception:
        await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(state="review",provider_id=provider_id)
        raise HTTPException(502, "未能确认图片生成结果，请凭请求编号核对", headers=headers) from None
    finally:
        if upstream is not None:
            await upstream.aclose()
        if client is not None:
            await client.aclose()
