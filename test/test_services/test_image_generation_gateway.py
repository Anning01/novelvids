import base64

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
