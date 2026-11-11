"""URL-only public image generation. Only the local studio retrieves the rendered files."""
import asyncio
import json
from ipaddress import ip_address
from math import isfinite
import time

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator

from auth.models import PlatformCallReceipt
from services.image_generation.adapters import ImageGenerationInput, image_protocol_adapter
from services.image_generation.capabilities import capabilities_for, validate_protocol, validate_selection
from services.platform.calls import CALL_TIMEOUT, admit, record_measurement


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
    model_config = ConfigDict(extra="forbid")
    model: str = Field(pattern=r"^nv-[1-9][0-9]{0,9}$")
    prompt: str = Field(min_length=1)
    size: str | None = Field(None, max_length=32)
    aspect_ratio: str | None = Field(None, max_length=16)
    n: int = Field(1, gt=0)
    output_format: str = Field("png", max_length=10)
    image: list[str] = Field(default_factory=list)
    frame_count: int | None = None
    frame_duration_ms: int | None = None
    response_format: str = Field("url", pattern="^url$")

    @field_validator("image")
    @classmethod
    def public_references(cls, values):
        return [media_url(v) for v in values]


def selection(config, body):
    caps = capabilities_for(config.image_model_type)
    size = body.get("size")
    ratio = body.get("aspect_ratio")
    if size and "x" in size:
        match = next(((tier, caps.aspect_ratios[sizes.index(size)]) for tier, sizes in caps.sizes.items() if size in sizes), None)
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
    selected = selection(config, body)
    pricing = config.pricing or {}
    price = (pricing.get("prices") or {}).get(selected.clarity)
    if pricing.get("type") != "image" or type(price) not in (float, int) or not isfinite(price) or price < 0:
        raise HTTPException(422, "所选清晰度尚未配置图片价格")
    return pricing


async def generate(ctx, request, key):
    body = request.model_dump(exclude_none=True)
    config, receipt = await admit(ctx, int(request.model[3:]), body, key, validate=image_options)
    headers = {"X-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    selected = selection(config, body)
    extra = {"image": request.image} if request.image else {}
    if selected.output_format == "gif":
        extra.update(frame_count=selected.frame_count, frame_duration_ms=selected.frame_duration_ms)
    prepared = image_protocol_adapter(config.api_protocol).prepare(ImageGenerationInput(
        model=config.model, prompt=request.prompt, resolution=selected.provider_size, aspect_ratio=selected.aspect_ratio,
        count=request.n, output_format=selected.output_format, quality=selected.provider_quality, extra_body=extra))
    provider_id = None
    try:
        async with asyncio.timeout(CALL_TIMEOUT), httpx.AsyncClient(timeout=CALL_TIMEOUT, follow_redirects=False) as client:
            async with client.stream("POST", config.base_url.rstrip("/") + prepared.path,
                headers={"Authorization":"Bearer "+config.api_key},
                json={**prepared.payload, "response_format":"url"}) as upstream:
                provider_id = upstream.headers.get("x-request-id")
                if 400 <= upstream.status_code < 500 and upstream.status_code != 408:
                    await PlatformCallReceipt.filter(id=receipt.id).update(state="rejected", provider_id=provider_id)
                    raise HTTPException(429 if upstream.status_code==429 else 422, "供应商未接受本次图片请求", headers=headers)
                upstream.raise_for_status()
                # The supplier must return a small JSON description, not a file or Base64 image body.
                length = upstream.headers.get("content-length")
                if length and int(length) > 1024*1024:
                    raise ValueError("Expected URL response")
                payload = bytearray()
                async for chunk in upstream.aiter_bytes(chunk_size=16*1024):
                    payload.extend(chunk)
                    if len(payload) > 1024*1024:
                        raise ValueError("Expected URL response")
        raw = json.loads(payload)
        if not isinstance(raw, dict) or raw.get("error"):
            raise ValueError("Missing image result")
        urls = [media_url(item.get("url") if isinstance(item, dict) else item) for item in raw.get("data",raw.get("images",[]))]
        if not urls or len(urls) > request.n:
            raise ValueError("Unconfirmed image count")
        await record_measurement(receipt, {"image_count":len(urls),"clarity":selected.clarity,"input_image_count":len(request.image)},provider_id)
        return JSONResponse({"created":int(time.time()),"model":request.model,"data":[{"url":url} for url in urls]}, headers=headers)
    except HTTPException:
        raise
    except Exception:
        await PlatformCallReceipt.filter(id=receipt.id,state="submitted").update(state="review",provider_id=provider_id)
        raise HTTPException(502, "未能确认图片生成结果，请凭请求编号核对", headers=headers) from None
