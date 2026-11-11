import pytest

from auth.models import User
from auth.security import hash_password
from config import settings
from test.test_services.test_legal_documents import configure_legal

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires auth")]


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/register", "/api/auth/change-password", "/api/team/members/1/reset-password", "/api/users"])
async def test_qiling_login_blocks_password_flows(client, monkeypatch, path):
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


async def test_documents_are_public_and_reflect_environment(client, monkeypatch):
    configure_legal(monkeypatch)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "password")
    for kind in ("terms", "privacy"):
        response = await client.get("/api/auth/legal/" + kind)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "测试运营者" in response.text and "【填写" not in response.text
    assert (await client.get("/api/auth/status")).json()["data"]["legal_ready"] is True
