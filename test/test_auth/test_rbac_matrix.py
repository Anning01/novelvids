"""RBAC 角色矩阵测试：四级角色 × 各路由的读写与数据可见性。

仅在 AUTH_ENABLED=true 时运行。
"""

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamMember, User
from auth.security import hash_password
from config import settings
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from utils.enums import AiTaskTypeEnum, TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时 RBAC 不生效"
)

PASSWORD = "password123"


async def _create_user(username: str, *, super_admin: bool = False) -> User:
    return await User.create(
        username=username,
        nickname=username,
        password_hash=hash_password(PASSWORD),
        is_super_admin=super_admin,
    )


async def _add_member(user: User, team: Team, role: str) -> None:
    await TeamMember.create(team=team, user=user, role=role)


async def _login(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def rbac_world(client: AsyncClient):
    """构造：团队A（管理员/创作者/查看者/第二个创作者）+ 团队B + 超管。"""
    team_a = await Team.create(name="矩阵A")
    team_b = await Team.create(name="矩阵B")
    admin = await _create_user("rbac_admin")
    creator = await _create_user("rbac_creator")
    creator2 = await _create_user("rbac_creator2")
    viewer = await _create_user("rbac_viewer")
    boss = await _create_user("rbac_boss", super_admin=True)
    await _add_member(admin, team_a, TeamRoleEnum.admin.value)
    await _add_member(creator, team_a, TeamRoleEnum.creator.value)
    await _add_member(creator2, team_a, TeamRoleEnum.creator.value)
    await _add_member(viewer, team_a, TeamRoleEnum.viewer.value)

    novel_a = await Novel.create(name="矩阵项目A", author="x", team_id=team_a.id)
    novel_b = await Novel.create(name="矩阵项目B", author="x", team_id=team_b.id)
    await ModelUsageRecord.create(
        novel_id=novel_a.id,
        task_type=AiTaskTypeEnum.extraction.value,
        billing_type="text",
        model="m",
        cost=10,
        team_id=team_a.id,
        user_id=creator.id,
    )
    await ModelUsageRecord.create(
        novel_id=novel_a.id,
        task_type=AiTaskTypeEnum.extraction.value,
        billing_type="text",
        model="m",
        cost=20,
        team_id=team_a.id,
        user_id=creator2.id,
    )
    await ModelUsageRecord.create(
        novel_id=novel_b.id,
        task_type=AiTaskTypeEnum.extraction.value,
        billing_type="text",
        model="m",
        cost=99,
        team_id=team_b.id,
    )

    tokens = {
        name: await _login(client, name)
        for name in ("rbac_admin", "rbac_creator", "rbac_creator2", "rbac_viewer", "rbac_boss")
    }
    return {
        "team_a": team_a,
        "team_b": team_b,
        "novel_a": novel_a,
        "novel_b": novel_b,
        "creator": creator,
        "creator2": creator2,
        "tokens": tokens,
    }


# ---------------------------------------------------------------- 读权限矩阵

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username,path,expected",
    [
        # 业务数据读取：四种角色 + 超管全部可读
        ("rbac_viewer", "/api/novel", 0),
        ("rbac_viewer", "/api/media-library/audio-references", 0),
        ("rbac_viewer", "/api/workbench/capabilities", 0),
        ("rbac_viewer", "/api/config/enums/all", 0),
        # 设置（模型配置 CRUD/通用配置）：创作者与查看者 403，管理员/超管可读
        ("rbac_creator", "/api/config", 403),
        ("rbac_creator", "/api/config/general", 403),
        ("rbac_viewer", "/api/config", 403),
        ("rbac_viewer", "/api/config/general", 403),
        ("rbac_admin", "/api/config", 0),
        ("rbac_boss", "/api/config", 0),
        # 成本：查看者 403，创作者/管理员/超管可读
        ("rbac_viewer", "/api/billing/summary", 403),
        ("rbac_creator", "/api/billing/summary", 0),
        ("rbac_admin", "/api/billing/summary", 0),
        ("rbac_boss", "/api/billing/summary", 0),
    ],
)
async def test_read_permission_matrix(client, rbac_world, username, path, expected):
    token = rbac_world["tokens"][username]
    response = await client.get(path, headers=_auth(token))
    assert response.json()["code"] == expected, f"{username} GET {path}: {response.text}"


@pytest.mark.asyncio
async def test_viewer_cannot_read_billing_records(client, rbac_world):
    token = rbac_world["tokens"]["rbac_viewer"]
    response = await client.get("/api/billing/records", headers=_auth(token))
    assert response.json()["code"] == 403


# ---------------------------------------------------------------- 写权限矩阵

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username,method,path,json,expected",
    [
        # 查看者：任何写操作 403
        ("rbac_viewer", "POST", "/api/novel", {"name": "v"}, 403),
        ("rbac_viewer", "POST", "/api/file/upload", None, 403),
        # 创作者：业务写操作放行
        ("rbac_creator", "POST", "/api/novel", {"name": "c"}, 0),
        # 创作者：设置写操作 403；管理员放行（以创建模型配置为例）
        ("rbac_creator", "POST", "/api/config", {
            "task_type": AiTaskTypeEnum.extraction.value,
            "name": "creator-cfg",
            "base_url": "https://x",
            "api_key": "k",
            "model": "m",
        }, 403),
        ("rbac_admin", "POST", "/api/config", {
            "task_type": AiTaskTypeEnum.extraction.value,
            "name": "admin-cfg",
            "base_url": "https://x",
            "api_key": "k",
            "model": "m",
        }, 0),
    ],
)
async def test_write_permission_matrix(client, rbac_world, username, method, path, json, expected):
    token = rbac_world["tokens"][username]
    kwargs = {"headers": _auth(token)}
    if json is not None:
        kwargs["json"] = json
    response = await client.request(method, path, **kwargs)
    assert response.json()["code"] == expected, f"{username} {method} {path}: {response.text}"


@pytest.mark.asyncio
async def test_anonymous_gets_401_on_protected_routes(client, rbac_world):
    for path in ("/api/novel", "/api/config", "/api/billing/summary", "/api/workbench/capabilities"):
        response = await client.get(path)
        assert response.json()["code"] == 401, f"anonymous GET {path}: {response.text}"


# ---------------------------------------------------------------- 成本可见性

@pytest.mark.asyncio
async def test_billing_admin_sees_whole_team(client, rbac_world):
    token = rbac_world["tokens"]["rbac_admin"]
    response = await client.get("/api/billing/summary", headers=_auth(token))
    data = response.json()["data"]
    assert data["total_cost"] == 30  # 团队A 两条


@pytest.mark.asyncio
async def test_billing_creator_sees_only_own_cost(client, rbac_world):
    token = rbac_world["tokens"]["rbac_creator"]
    response = await client.get("/api/billing/summary", headers=_auth(token))
    data = response.json()["data"]
    assert data["total_cost"] == 10  # 仅本人


@pytest.mark.asyncio
async def test_billing_super_admin_sees_all_teams(client, rbac_world):
    token = rbac_world["tokens"]["rbac_boss"]
    response = await client.get("/api/billing/summary", headers=_auth(token))
    data = response.json()["data"]
    assert data["total_cost"] == 129  # 10 + 20 + 99


# ---------------------------------------------------------------- 跨团队写拦截

@pytest.mark.asyncio
async def test_creator_cannot_write_other_team_novel(client, rbac_world):
    token = rbac_world["tokens"]["rbac_creator"]
    novel_b = rbac_world["novel_b"]
    response = await client.patch(
        f"/api/novel/{novel_b.id}", json={"author": "hack"}, headers=_auth(token)
    )
    assert response.json()["code"] == 404
