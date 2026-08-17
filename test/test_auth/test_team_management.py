"""成员与团队管理 API 测试（RBAC 与业务规则）。

仅在 AUTH_ENABLED=true 时运行。
"""

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamMember, User
from auth.security import hash_password, verify_password
from config import settings
from utils.enums import TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时管理功能未启用"
)

PASSWORD = "password123"


async def _create_user(username: str, *, super_admin: bool = False) -> User:
    return await User.create(
        username=username,
        nickname=username,
        password_hash=hash_password(PASSWORD),
        is_super_admin=super_admin,
    )


async def _login(client: AsyncClient, username: str, password: str = PASSWORD) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def member_world(client: AsyncClient):
    team = await Team.create(name="成员队")
    admin = await _create_user("mem_admin")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    viewer = await _create_user("mem_viewer")
    await TeamMember.create(team=team, user=viewer, role=TeamRoleEnum.viewer.value)
    creator = await _create_user("mem_creator")
    await TeamMember.create(team=team, user=creator, role=TeamRoleEnum.creator.value)
    boss = await _create_user("mem_boss", super_admin=True)
    tokens = {
        "admin": await _login(client, "mem_admin"),
        "viewer": await _login(client, "mem_viewer"),
        "creator": await _login(client, "mem_creator"),
        "boss": await _login(client, "mem_boss"),
    }
    return {
        "team": team,
        "admin": admin,
        "viewer": viewer,
        "creator": creator,
        "boss": boss,
        "tokens": tokens,
    }


@pytest.mark.asyncio
async def test_admin_lists_members(client, member_world):
    response = await client.get(
        "/api/team/members", headers=_auth(member_world["tokens"]["admin"])
    )
    assert response.json()["code"] == 0
    names = {item["username"] for item in response.json()["data"]["items"]}
    assert names == {"mem_admin", "mem_viewer", "mem_creator"}


@pytest.mark.asyncio
async def test_viewer_cannot_list_members(client, member_world):
    response = await client.get(
        "/api/team/members", headers=_auth(member_world["tokens"]["viewer"])
    )
    assert response.json()["code"] == 403


@pytest.mark.asyncio
async def test_admin_creates_invite_and_new_user_registers(client, member_world):
    """加入团队的唯一方式：邀请链接 → 新用户注册。"""
    invite = await client.post(
        "/api/team/invites?role=creator",
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert invite.json()["code"] == 0, invite.text
    token = invite.json()["data"]["token"]

    # 公开信息（不登录可读）
    info = await client.get(f"/api/team/invites/{token}")
    assert info.json()["code"] == 0
    assert info.json()["data"]["team_name"] == "成员队"

    # 新用户经链接注册
    registered = await client.post(
        "/api/auth/register",
        json={"username": "new_guy", "nickname": "新人", "password": "initial-pass-1", "invite_token": token},
    )
    assert registered.json()["code"] == 0, registered.text
    assert registered.json()["data"]["user"]["username"] == "new_guy"

    # 注册即登录，可访问业务
    session_token = registered.json()["data"]["token"]
    me = await client.get("/api/auth/me", headers=_auth(session_token))
    assert me.json()["code"] == 0
    assert me.json()["data"]["memberships"][0]["team_name"] == "成员队"


@pytest.mark.asyncio
async def test_register_duplicate_username_rejected(client, member_world):
    invite = await client.post(
        "/api/team/invites", headers=_auth(member_world["tokens"]["admin"])
    )
    token = invite.json()["data"]["token"]
    response = await client.post(
        "/api/auth/register",
        json={"username": "mem_viewer", "password": "whatever-123", "invite_token": token},
    )
    assert response.json()["code"] == 400


@pytest.mark.asyncio
async def test_admin_can_change_role_and_reset_password(client, member_world):
    viewer_id = member_world["viewer"].id
    changed = await client.patch(
        f"/api/team/members/{viewer_id}",
        json={"role": "creator"},
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert changed.json()["code"] == 0
    assert changed.json()["data"]["role"] == "creator"

    reset = await client.post(
        f"/api/team/members/{viewer_id}/reset-password",
        json={"new_password": "reset-pass-456"},
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert reset.json()["code"] == 0

    user = await User.get(id=viewer_id)
    assert verify_password("reset-pass-456", user.password_hash)


@pytest.mark.asyncio
async def test_admin_cannot_change_own_role_or_remove_self(client, member_world):
    admin_id = member_world["admin"].id
    changed = await client.patch(
        f"/api/team/members/{admin_id}",
        json={"role": "viewer"},
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert changed.json()["code"] == 400

    removed = await client.delete(
        f"/api/team/members/{admin_id}",
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert removed.json()["code"] == 400


@pytest.mark.asyncio
async def test_admin_removes_member(client, member_world):
    viewer_id = member_world["viewer"].id
    removed = await client.delete(
        f"/api/team/members/{viewer_id}",
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert removed.json()["code"] == 0
    assert await TeamMember.filter(team_id=member_world["team"].id, user_id=viewer_id).exists() is False


@pytest.mark.asyncio
async def test_creator_cannot_manage_members_or_invites(client, member_world):
    response = await client.post(
        "/api/team/invites",
        headers=_auth(member_world["tokens"]["creator"]),
    )
    assert response.json()["code"] == 403
    members = await client.get(
        "/api/team/members", headers=_auth(member_world["tokens"]["creator"])
    )
    assert members.json()["code"] == 403


@pytest.mark.asyncio
async def test_super_admin_manages_team_members(client, member_world):
    team_id = member_world["team"].id
    listing = await client.get(
        f"/api/team/members?team_id={team_id}", headers=_auth(member_world["tokens"]["boss"])
    )
    assert listing.json()["code"] == 0
    assert len(listing.json()["data"]["items"]) == 3

    # 超管也可为指定团队生成邀请
    invite = await client.post(
        f"/api/team/invites?team_id={team_id}&role=viewer",
        headers=_auth(member_world["tokens"]["boss"]),
    )
    assert invite.json()["code"] == 0


@pytest.mark.asyncio
async def test_teams_crud_super_only(client, member_world):
    token = member_world["tokens"]["boss"]
    created = await client.post(
        "/api/team/teams",
        json={"name": "新建团队", "owner_user_id": member_world["viewer"].id},
        headers=_auth(token),
    )
    assert created.json()["code"] == 0, created.text
    team_id = created.json()["data"]["id"]

    renamed = await client.patch(
        f"/api/team/teams/{team_id}", json={"name": "改名团队"}, headers=_auth(token)
    )
    assert renamed.json()["code"] == 0
    assert renamed.json()["data"]["name"] == "改名团队"

    stopped = await client.patch(
        f"/api/team/teams/{team_id}", json={"status": 0}, headers=_auth(token)
    )
    assert stopped.json()["data"]["status"] == 0

    listing = await client.get("/api/team/teams", headers=_auth(token))
    names = {item["name"] for item in listing.json()["data"]["items"]}
    assert "改名团队" in names

    # 团队管理员无权访问团队管理
    denied = await client.get("/api/team/teams", headers=_auth(member_world["tokens"]["admin"]))
    assert denied.json()["code"] == 403


@pytest.mark.asyncio
async def test_duplicate_team_name_rejected(client, member_world):
    token = member_world["tokens"]["boss"]
    response = await client.post(
        "/api/team/teams",
        json={"name": "成员队", "owner_user_id": member_world["viewer"].id},
        headers=_auth(token),
    )
    assert response.json()["code"] == 400


@pytest.mark.asyncio
async def test_disabled_team_blocks_member_access(client, member_world):
    """停用团队后，其成员访问业务接口被拒绝。"""
    team_id = member_world["team"].id
    await client.patch(
        f"/api/team/teams/{team_id}", json={"status": 0}, headers=_auth(member_world["tokens"]["boss"])
    )
    response = await client.get("/api/novel", headers=_auth(member_world["tokens"]["creator"]))
    assert response.json()["code"] == 403


@pytest.mark.asyncio
async def test_members_list_is_paginated(client, member_world):
    """成员量大时分页返回：第 1 页 20 条，第 2 页剩余。"""
    team = member_world["team"]
    for index in range(25):
        user = await _create_user(f"bulk_user_{index}")
        await TeamMember.create(team=team, user=user, role=TeamRoleEnum.creator.value)

    page1 = await client.get(
        "/api/team/members?page=1&page_size=20",
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert page1.json()["code"] == 0
    assert page1.json()["data"]["pagination"]["total"] == 28  # 原有 3 人 + 25
    assert page1.json()["data"]["pagination"]["pages"] == 2
    assert len(page1.json()["data"]["items"]) == 20

    page2 = await client.get(
        "/api/team/members?page=2&page_size=20",
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert len(page2.json()["data"]["items"]) == 8


@pytest.mark.asyncio
async def test_admin_cannot_set_own_limit_or_reset_own_password(client, member_world):
    """团队管理员不可对自己执行限额与重置密码操作。"""
    admin_id = member_world["admin"].id
    limit = await client.put(
        f"/api/team/members/{admin_id}/limit",
        json={"cost_limit": "10"},
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert limit.json()["code"] == 400

    reset = await client.post(
        f"/api/team/members/{admin_id}/reset-password",
        json={"new_password": "whatever-123"},
        headers=_auth(member_world["tokens"]["admin"]),
    )
    assert reset.json()["code"] == 400
