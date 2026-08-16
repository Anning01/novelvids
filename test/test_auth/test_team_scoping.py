"""团队数据隔离测试：项目列表/详情/创建/跨团队访问 + 存量回填迁移。

仅在 AUTH_ENABLED=true 时运行。
"""

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamMember, User
from auth.security import hash_password
from config import settings
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.schema_compat import ensure_team_schema
from utils.enums import AiTaskTypeEnum, TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时团队隔离不生效"
)


async def _create_team(name: str) -> Team:
    return await Team.create(name=name)


async def _create_member(
    username: str, team: Team, role: str = TeamRoleEnum.creator.value
) -> tuple[User, str]:
    user = await User.create(
        username=username,
        nickname=username,
        password_hash=hash_password("password123"),
    )
    await TeamMember.create(team=team, user=user, role=role)
    return user, f"{username}"


async def _login(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": "password123"}
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["token"]


async def _create_novel(name: str, team: Team | None = None, created_by: int | None = None) -> Novel:
    return await Novel.create(
        name=name,
        author="测试作者",
        team_id=team.id if team else None,
        created_by=created_by,
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_member_list_sees_only_own_team_novels(client: AsyncClient):
    team_a = await _create_team("团队A")
    team_b = await _create_team("团队B")
    await _create_member("alice", team_a)
    await _create_novel("A队项目", team=team_a)
    await _create_novel("B队项目", team=team_b)

    token = await _login(client, "alice")
    response = await client.get("/api/novel", headers=_auth(token))
    assert response.json()["code"] == 0
    names = [item["name"] for item in response.json()["data"]["items"]]
    assert names == ["A队项目"]


@pytest.mark.asyncio
async def test_member_cannot_access_other_team_novel(client: AsyncClient):
    team_a = await _create_team("团队A")
    team_b = await _create_team("团队B")
    await _create_member("alice", team_a)
    novel_b = await _create_novel("B队项目", team=team_b)

    token = await _login(client, "alice")
    detail = await client.get(f"/api/novel/{novel_b.id}", headers=_auth(token))
    assert detail.json()["code"] == 404
    update = await client.patch(
        f"/api/novel/{novel_b.id}", json={"author": "篡改"}, headers=_auth(token)
    )
    assert update.json()["code"] == 404
    delete = await client.delete(f"/api/novel/{novel_b.id}", headers=_auth(token))
    assert delete.json()["code"] == 404
    assert await Novel.filter(id=novel_b.id).exists()


@pytest.mark.asyncio
async def test_member_create_assigns_team_and_creator(client: AsyncClient):
    team_a = await _create_team("团队A")
    await _create_member("alice", team_a)

    token = await _login(client, "alice")
    response = await client.post(
        "/api/novel", json={"name": "新项目", "author": "张三"}, headers=_auth(token)
    )
    assert response.json()["code"] == 0, response.text
    novel = await Novel.get(name="新项目")
    assert novel.team_id == team_a.id
    alice = await User.get(username="alice")
    assert novel.created_by == alice.id


@pytest.mark.asyncio
async def test_super_admin_sees_all_teams(client: AsyncClient):
    team_a = await _create_team("团队A")
    team_b = await _create_team("团队B")
    await _create_novel("A队项目", team=team_a)
    await _create_novel("B队项目", team=team_b)
    boss = await User.create(
        username="boss",
        nickname="boss",
        password_hash=hash_password("password123"),
        is_super_admin=True,
    )

    token = await _login(client, "boss")
    response = await client.get("/api/novel", headers=_auth(token))
    names = sorted(item["name"] for item in response.json()["data"]["items"])
    assert names == ["A队项目", "B队项目"]

    novel_b = await Novel.get(name="B队项目")
    detail = await client.get(f"/api/novel/{novel_b.id}", headers=_auth(token))
    assert detail.json()["code"] == 0


@pytest.mark.asyncio
async def test_user_without_team_membership_gets_403(client: AsyncClient):
    await User.create(
        username="lonely",
        nickname="lonely",
        password_hash=hash_password("password123"),
    )
    token = await _login(client, "lonely")
    response = await client.get("/api/novel", headers=_auth(token))
    assert response.json()["code"] == 403


@pytest.mark.asyncio
async def test_anonymous_gets_401_when_auth_enabled(client: AsyncClient):
    response = await client.get("/api/novel")
    assert response.json()["code"] == 401


@pytest.mark.asyncio
async def test_ensure_team_schema_backfills_legacy_data(client: AsyncClient):
    """存量数据（team_id 为空）在首次启用登录时回填到默认团队。"""
    novel_a = await _create_novel("存量项目A")
    novel_b = await _create_novel("存量项目B")
    await ModelUsageRecord.create(
        novel_id=novel_a.id,
        task_type=AiTaskTypeEnum.extraction.value,
        billing_type="text",
        model="legacy-model",
        cost=1.5,
        team_id=None,
        user_id=None,
    )

    await ensure_team_schema()
    await ensure_team_schema()  # 幂等

    teams = await Team.all()
    assert len(teams) == 1
    default_team = teams[0]
    assert default_team.name == "默认团队"
    assert (await Novel.get(id=novel_a.id)).team_id == default_team.id
    assert (await Novel.get(id=novel_b.id)).team_id == default_team.id
    record = await ModelUsageRecord.first()
    assert record.team_id == default_team.id


@pytest.mark.asyncio
async def test_ensure_team_schema_skips_when_no_orphans(client: AsyncClient):
    team_a = await _create_team("团队A")
    await _create_novel("已归属项目", team=team_a)
    await ensure_team_schema()
    # 已有团队且无孤儿数据：不应新建默认团队
    assert await Team.filter(name="默认团队").count() == 0
