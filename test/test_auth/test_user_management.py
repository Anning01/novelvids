"""超管用户管理测试：统计、列表、手动创建、禁用登录、删除约束、团队所有人约束。

仅在 AUTH_ENABLED=true 时运行。
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamMember, User
from auth.security import hash_password
from config import settings
from utils.enums import TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时用户管理未启用"
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
    return response.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def user_world(client: AsyncClient):
    boss = await _create_user("um_boss", super_admin=True)
    alice = await _create_user("um_alice")
    bob = await _create_user("um_bob")
    team = await Team.create(name="用户管理队", owner_user_id=alice.id)
    await TeamMember.create(team=team, user=alice, role=TeamRoleEnum.admin.value)
    await TeamMember.create(team=team, user=bob, role=TeamRoleEnum.creator.value)
    login = await _login(client, "um_boss")
    return {
        "boss": boss,
        "alice": alice,
        "bob": bob,
        "team": team,
        "token": login["data"]["token"],
    }


# ---------------------------------------------------------------- 统计与列表


@pytest.mark.asyncio
async def test_user_stats(client, user_world):
    await TeamMember.filter(user=user_world["bob"]).update(total_cost=Decimal("12.5"))
    response = await client.get("/api/users/stats", headers=_auth(user_world["token"]))
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    assert data["user_count"] == 3  # boss + alice + bob
    assert data["team_count"] == 1
    assert data["user_total_cost"] == 12.5
    assert data["team_balance_total"] == 0.0


@pytest.mark.asyncio
async def test_user_list_with_costs_and_teams(client, user_world):
    await TeamMember.filter(user=user_world["alice"]).update(total_cost=Decimal("5"))
    response = await client.get("/api/users", headers=_auth(user_world["token"]))
    assert response.json()["code"] == 0, response.text
    items = {item["username"]: item for item in response.json()["data"]["items"]}
    assert set(items) == {"um_boss", "um_alice", "um_bob"}
    assert items["um_alice"]["total_cost"] == 5.0
    assert items["um_alice"]["team_count"] == 1
    assert items["um_boss"]["is_super_admin"] is True


@pytest.mark.asyncio
async def test_user_management_is_super_only(client, user_world):
    alice_login = await _login(client, "um_alice")
    response = await client.get(
        "/api/users", headers=_auth(alice_login["data"]["token"])
    )
    assert response.json()["code"] == 403


# ---------------------------------------------------------------- 手动创建与禁用


@pytest.mark.asyncio
async def test_super_creates_user_manually(client, user_world):
    response = await client.post(
        "/api/users",
        json={"username": "manual_guy", "password": "manual-pass-1", "nickname": "手动哥"},
        headers=_auth(user_world["token"]),
    )
    assert response.json()["code"] == 0, response.text
    assert response.json()["data"]["username"] == "manual_guy"
    assert response.json()["data"]["team_count"] == 0

    duplicate = await client.post(
        "/api/users",
        json={"username": "manual_guy", "password": "manual-pass-1"},
        headers=_auth(user_world["token"]),
    )
    assert duplicate.json()["code"] == 400


@pytest.mark.asyncio
async def test_super_disables_user_login(client, user_world):
    bob_id = user_world["bob"].id
    disabled = await client.patch(
        f"/api/users/{bob_id}", json={"status": 0}, headers=_auth(user_world["token"])
    )
    assert disabled.json()["code"] == 0
    assert disabled.json()["data"]["status"] == 0

    # 被禁用后无法登录
    login = await _login(client, "um_bob")
    assert login["code"] == 403

    # 恢复
    restored = await client.patch(
        f"/api/users/{bob_id}", json={"status": 1}, headers=_auth(user_world["token"])
    )
    assert restored.json()["data"]["status"] == 1


@pytest.mark.asyncio
async def test_cannot_disable_self_or_super(client, user_world):
    boss_id = user_world["boss"].id
    self_change = await client.patch(
        f"/api/users/{boss_id}", json={"status": 0}, headers=_auth(user_world["token"])
    )
    assert self_change.json()["code"] == 400

    other_super = await _create_user("um_boss2", super_admin=True)
    change = await client.patch(
        f"/api/users/{other_super.id}",
        json={"status": 0},
        headers=_auth(user_world["token"]),
    )
    assert change.json()["code"] == 400


# ---------------------------------------------------------------- 删除约束


@pytest.mark.asyncio
async def test_cannot_delete_team_owner(client, user_world):
    alice_id = user_world["alice"].id
    response = await client.delete(
        f"/api/users/{alice_id}", headers=_auth(user_world["token"])
    )
    assert response.json()["code"] == 400
    assert "所有人" in response.json()["message"]


@pytest.mark.asyncio
async def test_delete_user_cascades_membership(client, user_world):
    bob_id = user_world["bob"].id
    response = await client.delete(
        f"/api/users/{bob_id}", headers=_auth(user_world["token"])
    )
    assert response.json()["code"] == 0, response.text
    assert await User.filter(id=bob_id).exists() is False
    assert await TeamMember.filter(user_id=bob_id).exists() is False


@pytest.mark.asyncio
async def test_cannot_delete_self_or_super(client, user_world):
    boss_id = user_world["boss"].id
    self_delete = await client.delete(
        f"/api/users/{boss_id}", headers=_auth(user_world["token"])
    )
    assert self_delete.json()["code"] == 400

    other_super = await _create_user("um_boss3", super_admin=True)
    delete_super = await client.delete(
        f"/api/users/{other_super.id}", headers=_auth(user_world["token"])
    )
    assert delete_super.json()["code"] == 400


# ---------------------------------------------------------------- 团队所有人


@pytest.mark.asyncio
async def test_create_team_requires_owner_and_auto_admin(client, user_world):
    response = await client.post(
        "/api/team/teams",
        json={"name": "所有人队", "owner_user_id": user_world["bob"].id},
        headers=_auth(user_world["token"]),
    )
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    assert data["owner_user_id"] == user_world["bob"].id
    assert data["owner_username"] == "um_bob"
    assert data["member_count"] == 1

    membership = await TeamMember.get_or_none(
        team_id=data["id"], user_id=user_world["bob"].id
    )
    assert membership is not None
    assert membership.role == TeamRoleEnum.admin.value


@pytest.mark.asyncio
async def test_create_team_allows_super_as_owner(client, user_world):
    """超管也可以被指定为团队所有人（自动成为该团队管理员）。"""
    response = await client.post(
        "/api/team/teams",
        json={"name": "超管所有人队", "owner_user_id": user_world["boss"].id},
        headers=_auth(user_world["token"]),
    )
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    assert data["owner_user_id"] == user_world["boss"].id
    membership = await TeamMember.get_or_none(
        team_id=data["id"], user_id=user_world["boss"].id
    )
    assert membership is not None
    assert membership.role == TeamRoleEnum.admin.value


@pytest.mark.asyncio
async def test_create_team_rejects_missing_owner(client, user_world):
    response = await client.post(
        "/api/team/teams",
        json={"name": "无所有人队", "owner_user_id": 99999},
        headers=_auth(user_world["token"]),
    )
    assert response.json()["code"] == 404
