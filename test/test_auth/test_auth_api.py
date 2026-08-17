"""鉴权 API 测试：登录 / 当前用户 / 登出 / 修改密码 / 会话过期 / 超管引导。

仅在 AUTH_ENABLED=true 时运行（见模块级 skipif）。
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from auth.bootstrap import ensure_super_admin
from auth.models import Team, TeamMember, User, UserSession
from auth.security import hash_password, hash_token
from config import settings
from utils.enums import TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时 auth 模块未注册"
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_user(
    username: str = "alice",
    password: str = "password123",
    *,
    super_admin: bool = False,
) -> User:
    return await User.create(
        username=username,
        nickname=username,
        password_hash=hash_password(password),
        is_super_admin=super_admin,
    )


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    return response.json()


@pytest.mark.asyncio
async def test_login_success_and_me(client: AsyncClient):
    await _create_user()
    payload = await _login(client, "alice", "password123")
    assert payload["code"] == 0, payload
    token = payload["data"]["token"]
    assert payload["data"]["user"]["username"] == "alice"

    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["code"] == 0
    assert me.json()["data"]["user"]["username"] == "alice"
    assert me.json()["data"]["is_super_admin"] is False


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await _create_user()
    payload = await _login(client, "alice", "wrong-password")
    assert payload["code"] == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client: AsyncClient):
    payload = await _login(client, "nobody", "password123")
    assert payload["code"] == 401


@pytest.mark.asyncio
async def test_disabled_user_cannot_login(client: AsyncClient):
    await _create_user()
    await User.filter(username="alice").update(status=0)
    payload = await _login(client, "alice", "password123")
    assert payload["code"] == 403


@pytest.mark.asyncio
async def test_me_without_token(client: AsyncClient):
    me = await client.get("/api/auth/me")
    assert me.json()["code"] == 401


@pytest.mark.asyncio
async def test_me_with_invalid_token(client: AsyncClient):
    me = await client.get("/api/auth/me", headers=_auth("bogus-token"))
    assert me.json()["code"] == 401


@pytest.mark.asyncio
async def test_logout_revokes_session(client: AsyncClient):
    await _create_user()
    payload = await _login(client, "alice", "password123")
    token = payload["data"]["token"]

    logout = await client.post("/api/auth/logout", headers=_auth(token))
    assert logout.json()["code"] == 0

    me = await client.get("/api/auth/me", headers=_auth(token))
    assert me.json()["code"] == 401


@pytest.mark.asyncio
async def test_expired_session_rejected_and_deleted(client: AsyncClient):
    user = await _create_user()
    session = await UserSession.create(
        token_hash=hash_token("expired-token"),
        user=user,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    me = await client.get("/api/auth/me", headers=_auth("expired-token"))
    assert me.json()["code"] == 401
    assert await UserSession.filter(id=session.id).exists() is False


@pytest.mark.asyncio
async def test_change_password_flow(client: AsyncClient):
    await _create_user()
    payload = await _login(client, "alice", "password123")
    token = payload["data"]["token"]

    wrong_old = await client.post(
        "/api/auth/change-password",
        json={"old_password": "wrong", "new_password": "new-password-456"},
        headers=_auth(token),
    )
    assert wrong_old.json()["code"] == 400

    ok = await client.post(
        "/api/auth/change-password",
        json={"old_password": "password123", "new_password": "new-password-456"},
        headers=_auth(token),
    )
    assert ok.json()["code"] == 0

    old_login = await _login(client, "alice", "password123")
    assert old_login["code"] == 401
    new_login = await _login(client, "alice", "new-password-456")
    assert new_login["code"] == 0


@pytest.mark.asyncio
async def test_change_password_requires_login(client: AsyncClient):
    response = await client.post(
        "/api/auth/change-password",
        json={"old_password": "a", "new_password": "b" * 8},
    )
    assert response.json()["code"] == 401


@pytest.mark.asyncio
async def test_me_includes_membership(client: AsyncClient):
    user = await _create_user()
    team = await Team.create(name="测试团队")
    await TeamMember.create(team=team, user=user, role=TeamRoleEnum.creator.value)

    payload = await _login(client, "alice", "password123")
    me = await client.get("/api/auth/me", headers=_auth(payload["data"]["token"]))
    data = me.json()["data"]
    assert len(data["memberships"]) == 1
    assert data["memberships"][0]["team_id"] == team.id
    assert data["memberships"][0]["team_name"] == "测试团队"
    assert data["memberships"][0]["role"] == "creator"
    assert data["memberships"][0]["cost_limit"] is None
    assert data["memberships"][0]["team_balance"] == 0.0


@pytest.mark.asyncio
async def test_ensure_super_admin_creates_once(monkeypatch):
    monkeypatch.setattr(settings, "SUPER_ADMIN_USERNAME", "boss")
    monkeypatch.setattr(settings, "SUPER_ADMIN_PASSWORD", "boss-password-123")

    await ensure_super_admin()
    assert await User.filter(is_super_admin=True).count() == 1

    # 再次调用不应重复创建
    await ensure_super_admin()
    assert await User.filter(is_super_admin=True).count() == 1


@pytest.mark.asyncio
async def test_ensure_super_admin_skips_without_env(monkeypatch):
    monkeypatch.setattr(settings, "SUPER_ADMIN_USERNAME", "")
    monkeypatch.setattr(settings, "SUPER_ADMIN_PASSWORD", "")
    await ensure_super_admin()
    assert await User.filter(is_super_admin=True).count() == 0


@pytest.mark.asyncio
async def test_ensure_super_admin_skips_occupied_username(monkeypatch):
    await _create_user(username="boss")
    monkeypatch.setattr(settings, "SUPER_ADMIN_USERNAME", "boss")
    monkeypatch.setattr(settings, "SUPER_ADMIN_PASSWORD", "boss-password-123")
    await ensure_super_admin()
    assert await User.filter(is_super_admin=True).count() == 0
