import base64
import json
from email import policy
from email.parser import BytesParser

import httpx
import pytest

from services.image_generation.adapters import (
    ImageGenerationInput,
    image_protocol_adapter,
)
from services.image_generation.gateway import (
    ImageGenerationError,
    _safe_endpoint,
    generate_images,
)


@pytest.mark.parametrize("model", ["gpt-image-2.5", "gpt-image-2.6", "gpt-image-2.6-sunburst", "gpt-image-2.6-flare"])
@pytest.mark.parametrize("clarity,size", [("1K", "1024x1024"), ("2K", "2048x2048"), ("4K", "4096x4096")])
@pytest.mark.parametrize("base_url", ["https://image.example.com/v1", "https://other.example.com/custom/v1/"])
async def test_gpt_image_generation_uses_configured_provider_and_model(monkeypatch, model, base_url, clarity, size):
    from services.image_generation.capabilities import validate_selection
    from services.reference.generator import generate_for_sora_consistency

    selection = validate_selection(model.replace("-", "_").replace(".", "_"),
        clarity=clarity, aspect_ratio="1:1", output_format="png", generation_count=1)

    async def handler(request):
        assert str(request.url) == base_url.rstrip("/") + "/images/generations"
        assert request.headers["content-type"] == "application/json"
        assert json.loads(request.content) == {"model": model, "prompt": "a mug", "size": size,
            "quality": "high", "n": 1, "output_format": "png"}
        return httpx.Response(200, json={"data": [{"b64_json": "generated"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    images = await generate_for_sora_consistency({"base_traits": "a mug"}, base_url=base_url,
        api_key="secret", model=model, resolution=selection.provider_size, quality=selection.provider_quality)
    assert images[0].b64_json == "generated"


@pytest.mark.parametrize("model", ["gpt-image-2.5", "gpt-image-2.6", "gpt-image-2.6-sunburst", "gpt-image-2.6-flare"])
@pytest.mark.parametrize("source_kind", ["data", "url", "local", "multiple"])
async def test_openai_edits_uploads_reference_files(monkeypatch, tmp_path, source_kind, model):
    content = b"\x89PNG\r\n\x1a\nreference-image"
    data_uri = "data:image/png;base64," + base64.b64encode(content).decode()
    local = tmp_path / "reference.png"
    local.write_bytes(content)
    references = {"data": [data_uri], "url": ["https://cdn.example.com/ref.png?signature=private"],
        "local": [str(local)], "multiple": [data_uri, str(local)]}[source_kind]
    requests = []

    async def handler(request):
        requests.append(request)
        if request.method == "GET":
            assert request.url.host == "cdn.example.com"
            assert "authorization" not in request.headers
            return httpx.Response(200, content=content, headers={"content-type": "image/png"})
        assert request.url == "https://custom.example.com/proxy/v1/images/edits"
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
        parts = list(message.iter_parts())
        fields = {part.get_param("name", header="content-disposition"): part.get_content()
            for part in parts if not part.get_filename()}
        assert fields == {"model": model, "prompt": "replace background",
            "size": "1024x1024", "quality": "high", "n": "1", "output_format": "png"}
        files = [part for part in parts if part.get_filename()]
        assert len(files) == len(references)
        for part in files:
            assert part.get_param("name", header="content-disposition") == ("image" if len(files) == 1 else "image[]")
            assert part.get_content_type() == "image/png"
            assert part.get_payload(decode=True) == content
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example.com/edited.png"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    images = await generate_images(base_url="https://custom.example.com/proxy/v1/", api_key="secret",
        model=model, prompt="replace background", resolution="1024x1024",
        quality="high", extra_body={"image": references})
    assert images[0].url == "https://cdn.example.com/edited.png"
    assert len(requests) == (2 if source_kind == "url" else 1)


def test_openai_adapter_maps_resolution_alias_to_supported_vertical_size():
    prepared = image_protocol_adapter("openai_compatible").prepare(
        ImageGenerationInput(
            model="gpt-image-2",
            prompt="cover",
            resolution="2K",
            aspect_ratio="2:3",
        )
    )

    assert prepared.path == "/images/generations"
    assert prepared.payload == {
        "model": "gpt-image-2",
        "prompt": "cover",
        "n": 1,
        "size": "1024x1536",
        "output_format": "png",
        "quality": "high",
    }


def test_volcengine_adapter_sends_sequential_flag_only_for_seedream_3():
    # Seedream 3.0 支持 sequential_image_generation；4.0/5.0 已移除，传入会被 400 拒绝
    prepared = image_protocol_adapter("volcengine_ark").prepare(
        ImageGenerationInput(
            model="doubao-seedream-3-0-t2i-250421",
            prompt="cover",
            resolution="2K",
            aspect_ratio="2:3",
            count=3,
        )
    )

    assert prepared.payload == {
        "model": "doubao-seedream-3-0-t2i-250421",
        "prompt": "cover",
        "response_format": "url",
        "watermark": False,
        "sequential_image_generation": "disabled",
        "size": "2K",
        "output_format": "png",
    }


def test_volcengine_adapter_omits_sequential_flag_for_seedream_5():
    # 用户实测：Seedream 5.0（doubao-seedream-5-0-pro-260628）不支持
    # sequential_image_generation，Ark 返回 HTTP 400 InvalidParameter
    prepared = image_protocol_adapter("volcengine_ark").prepare(
        ImageGenerationInput(
            model="doubao-seedream-5-0-pro-260628",
            prompt="cover",
            resolution="2K",
            aspect_ratio="2:3",
            count=3,
        )
    )

    assert prepared.payload == {
        "model": "doubao-seedream-5-0-pro-260628",
        "prompt": "cover",
        "response_format": "url",
        "watermark": False,
        "size": "2K",
        "output_format": "png",
    }
    assert "sequential_image_generation" not in prepared.payload


def test_openrouter_adapter_uses_images_endpoint_and_native_dimensions():
    prepared = image_protocol_adapter("openrouter_compatible").prepare(
        ImageGenerationInput(
            model="configured-image-model",
            prompt="cover",
            resolution="2K",
            aspect_ratio="2:3",
            count=2,
        )
    )

    assert prepared.path == "/images"
    assert prepared.payload == {
        "model": "configured-image-model",
        "prompt": "cover",
        "n": 2,
        "output_format": "png",
        "resolution": "2K",
        "aspect_ratio": "2:3",
    }


def test_openrouter_adapter_sends_explicit_size_without_conflicting_aspect_ratio():
    prepared = image_protocol_adapter("openrouter_compatible").prepare(
        ImageGenerationInput(
            model="configured-image-model",
            prompt="cover",
            resolution="2048x1152",
            aspect_ratio="16:9",
        )
    )

    assert prepared.path == "/images"
    assert prepared.payload == {
        "model": "configured-image-model",
        "prompt": "cover",
        "n": 1,
        "output_format": "png",
        "size": "2048x1152",
    }


def test_openrouter_preserves_fixed_high_quality_independent_of_size():
    prepared = image_protocol_adapter("openrouter_compatible").prepare(ImageGenerationInput(
        model="supplier-alias", prompt="cover", resolution="4096x4096", quality="high"))
    assert prepared.payload["size"] == "4096x4096"
    assert prepared.payload["quality"] == "high"


def test_boundary_log_endpoint_removes_credentials_and_query_values():
    assert _safe_endpoint(
        "https://user:password@image.example.com:8443/v1/images/generations?token=secret"
    ) == "https://image.example.com:8443/v1/images/generations"


@pytest.mark.asyncio
async def test_gateway_normalizes_url_and_base64_responses(monkeypatch):
    encoded = base64.b64encode(b"image").decode()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://image.example.com/v1/images/generations"
        assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            headers={"x-request-id": "image-request-1"},
            json={
                "data": [
                    {"url": "https://cdn.example.com/cover.png"},
                    {"b64_json": encoded},
                ]
            },
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient", client_factory)

    images = await generate_images(
        base_url="https://image.example.com/v1",
        api_key="secret",
        model="image-model",
        prompt="cover",
    )

    assert images[0].url == "https://cdn.example.com/cover.png"
    assert images[1].b64_json == encoded


@pytest.mark.asyncio
async def test_gateway_rejects_success_response_without_images(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "empty-request"},
            json={"data": []},
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient", client_factory)

    with pytest.raises(ImageGenerationError, match="empty-request"):
        await generate_images(
            base_url="https://image.example.com/v1",
            api_key="secret",
            model="image-model",
            prompt="cover",
        )


@pytest.mark.asyncio
async def test_gateway_rejects_http_200_provider_error_envelope(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": {
                    "message": "sensitive upstream detail",
                    "code": 404,
                    "metadata": {
                        "router_code": "ROUTER_HTTP_ERROR",
                        "original_status_code": 404,
                        "request_id": "embedded-request-id",
                    },
                }
            },
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient", client_factory)

    with pytest.raises(
        ImageGenerationError,
        match=r"ROUTER_HTTP_ERROR.*上游 HTTP 404.*embedded-request-id",
    ) as exc_info:
        await generate_images(
            base_url="https://image.example.com/v1",
            api_key="secret",
            model="image-model",
            prompt="cover",
        )

    assert "sensitive upstream detail" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_gateway_includes_provider_error_message_on_http_error(monkeypatch):
    """4xx 响应体里的 error.message / error.code 应透传到前端（豆包/智谱/通义通用）。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            headers={"x-request-id": "req-arrearage"},
            json={
                "error": {
                    "code": "Arrearage",
                    "message": "账户余额不足，请充值后再试",
                }
            },
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient", client_factory)

    with pytest.raises(
        ImageGenerationError,
        match=r"账户余额不足.*Arrearage.*HTTP 402.*req-arrearage",
    ) as exc_info:
        await generate_images(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="secret",
            model="doubao-seedream-5-0-pro",
            prompt="cover",
        )
    assert "HTTP 402" in str(exc_info.value)
    assert "账户余额不足" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gateway_falls_back_to_plain_http_error_when_body_not_json(monkeypatch):
    """4xx 响应体非 JSON 时回退到旧格式（只显示状态码 + request_id），不抛解析错。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            headers={"x-request-id": "bad-gateway"},
            content=b"<html>Bad Gateway</html>",
        )

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.image_generation.gateway.httpx.AsyncClient", client_factory)

    with pytest.raises(
        ImageGenerationError,
        match=r"HTTP 502，request_id=bad-gateway",
    ):
        await generate_images(
            base_url="https://image.example.com/v1",
            api_key="secret",
            model="image-model",
            prompt="cover",
        )


@pytest.mark.parametrize("receipt_header", [None, "X-Novelvids-Request-Id", "X-Cat-Request-Id"])
async def test_only_retries_cat_capacity_rejections_before_admission(monkeypatch, receipt_header):
    from unittest.mock import AsyncMock
    attempts = []

    async def respond(request):
        attempts.append(request.headers["Idempotency-Key"])
        if len(attempts) == 1:
            headers = {"Retry-After": "2"}
            if receipt_header:
                headers[receipt_header] = "a-platform-receipt"
            return httpx.Response(429, headers=headers, json={"error": {
                "type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "模型并发已满，请稍后重试"}})
        return httpx.Response(200, json={"data": [{"url": "https://example.invalid/result.png"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real(**kwargs, transport=httpx.MockTransport(respond)))
    pause = AsyncMock()
    monkeypatch.setattr('asyncio.sleep', pause)
    call = generate_images(base_url="https://example.invalid/v1", api_key="test", model="nv-26",
                           prompt="test", api_protocol="novelvids")
    if receipt_header:
        with pytest.raises(ImageGenerationError):
            await call
        assert len(attempts) == 1
        pause.assert_not_awaited()
    else:
        assert (await call)[0].url.endswith("result.png")
        assert len(attempts) == 2 and len(set(attempts)) == 1
        pause.assert_awaited_once_with(2)
