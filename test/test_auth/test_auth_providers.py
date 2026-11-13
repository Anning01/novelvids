import asyncio
import os
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest

from auth import qiling
from auth.models import User
from auth.security import hash_password
from config import settings
from test.test_auth import issue_test_session
from test.test_services.test_legal_documents import configure_legal

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires auth")]


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/register", "/api/auth/change-password", "/api/team/members/1/reset-password", "/api/users"])
async def test_qiling_login_blocks_password_flows(client, monkeypatch, path):
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "platform")
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "qiling")
    result = await client.post(path, json={"username": "legacy", "password": "password123"})
    assert result.json()["code"] == 404


async def test_password_login_is_independent_of_qiling(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "password")
    monkeypatch.setattr(settings, "QILING_API_BASE_URL", "https://configured-but-disabled.example.test")
    await User.create(username="local-user", password_hash=hash_password("password123"))
    status = (await client.get("/api/auth/status")).json()["data"]
    assert status["provider"] == "password" and not status["qiling_enabled"]
    reply = (await client.post("/api/auth/login", json={"username": "local-user", "password": "password123"})).json()
    assert reply["code"] == 0
    for path in ("/api/auth/qiling/start", "/api/auth/qiling/poll"):
        response = await client.post(path, json={"attempt": "a" * 32})
        assert response.json()["code"] == 404


@pytest.mark.parametrize("role,provider", [("studio", "password"), ("platform", "qiling")])
async def test_configured_qiling_login_is_platform_only(role, provider):
    await asyncio.to_thread(subprocess.run, [sys.executable, "-c", """
import asyncio, os
import httpx
from config import settings
from main import app

async def check():
    platform = os.environ['NOVELVIDS_ROLE'] == 'platform'
    assert bool(settings.QILING_API_BASE_URL) == platform
    assert settings.QILING_SIGNUP_ENABLED == platform
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        data = (await client.get('/api/auth/status')).json()['data']
        assert data['provider'] == os.environ['TEST_EXPECTED_PROVIDER']
        assert data['qiling_enabled'] == platform
        if not platform:
            for endpoint in ('start', 'poll'):
                response = await client.post('/api/auth/qiling/' + endpoint, json={'attempt': 'a' * 32})
                assert response.json()['code'] == 404

asyncio.run(check())
"""], env={**os.environ, "NOVELVIDS_ROLE": role, "AUTH_ENABLED": "true", "AUTH_PROVIDER": "qiling",
    "QILING_API_BASE_URL": "https://issuer.example.test", "QILING_SIGNUP_ENABLED": "true", "TEST_EXPECTED_PROVIDER": provider}, check=True)


async def test_studio_blocks_qiling_binding_even_for_a_signed_in_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "DEPLOYMENT_ROLE", "studio")
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "qiling")
    monkeypatch.setattr(settings, "QILING_API_BASE_URL", "https://issuer.example.test")
    upstream = AsyncMock()
    monkeypatch.setattr(qiling, "_request", upstream)
    user = await User.create(username="local-admin", is_super_admin=True)
    headers = {"Authorization": "Bearer " + await issue_test_session(user.username)}
    for endpoint in ("start", "poll"):
        response = await client.post(f"/api/auth/qiling/bind/{endpoint}", headers=headers, json={"attempt": "a" * 32})
        assert response.json()["code"] == 404
    upstream.assert_not_awaited()


async def test_documents_are_public_and_reflect_environment(client, monkeypatch):
    configure_legal(monkeypatch)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "password")
    for kind in ("terms", "privacy"):
        response = await client.get("/api/auth/legal/" + kind)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "测试运营者" in response.text and "【填写" not in response.text
    assert (await client.get("/api/auth/status")).json()["data"]["legal_ready"] is True
