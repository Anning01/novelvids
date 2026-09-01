from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.requests import Request

from exceptions.handlers import global_exception_handler
from services.security.headers import SecurityHeadersMiddleware
from services.security.login_throttle import client_ip


@pytest.mark.asyncio
async def test_security_headers_apply_strict_app_and_docs_policies():
    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        content_security_policy="default-src 'self'",
        docs_content_security_policy="script-src https://docs.example",
    )

    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/docs")
    async def docs():
        return {"docs": True}

    @app.get("/media/covers/derivatives/cover-thumbnail.webp")
    async def derivative():
        return {"image": True}

    @app.get("/media/videos/posters/7-thumbnail.webp")
    async def poster():
        return {"poster": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        normal = await client.get("/health")
        docs = await client.get("/docs")
        image = await client.get(
            "/media/covers/derivatives/cover-thumbnail.webp"
        )
        missing_image = await client.get(
            "/media/covers/derivatives/missing-thumbnail.webp"
        )
        poster_image = await client.get("/media/videos/posters/7-thumbnail.webp")

    assert normal.headers["content-security-policy"] == "default-src 'self'"
    assert normal.headers["strict-transport-security"].startswith("max-age=")
    assert normal.headers["x-content-type-options"] == "nosniff"
    assert normal.headers["x-frame-options"] == "DENY"
    assert docs.headers["content-security-policy"] == "script-src https://docs.example"
    assert image.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )
    assert missing_image.status_code == 404
    assert "cache-control" not in missing_image.headers
    assert poster_image.headers["cache-control"] == (
        "public, max-age=31536000, immutable"
    )


def test_client_ip_only_trusts_forwarded_headers_from_configured_proxy(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "TRUSTED_PROXY_NETWORKS", ["127.0.0.1/32"])

    trusted = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.8, 127.0.0.1")],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 443),
        "scheme": "https",
        "query_string": b"",
    })
    untrusted = Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.8")],
        "client": ("198.51.100.4", 50000),
        "server": ("test", 443),
        "scheme": "https",
        "query_string": b"",
    })

    assert client_ip(trusted) == "203.0.113.8"
    assert client_ip(untrusted) == "198.51.100.4"


@pytest.mark.asyncio
async def test_production_error_response_does_not_expose_exception_text(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "EXPOSE_INTERNAL_ERRORS", False)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/private",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 443),
        "scheme": "https",
        "query_string": b"",
    })

    response = await global_exception_handler(
        request, RuntimeError("provider key sk-sensitive-value")
    )

    assert response.status_code == 500
    assert b"sk-sensitive-value" not in response.body
    assert "服务器内部错误".encode() in response.body
