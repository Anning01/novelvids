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
async def test_project_overview_uses_the_same_team_scope_for_cards_and_totals(client: AsyncClient):
    from models.chapter import Chapter

    team_a = await _create_team("Overview A")
    team_b = await _create_team("Overview B")
    await _create_member("overview_viewer", team_a, role=TeamRoleEnum.viewer.value)
    own = await _create_novel("Own overview", team_a)
    foreign = await _create_novel("Foreign overview", team_b)
    for project in (own, foreign):
        await Chapter.create(novel=project, number=1, name="Episode", content="Private manuscript")
    token = await _login(client, "overview_viewer")
    payload = (await client.get("/api/novel/overview", headers=_auth(token))).json()
    assert payload["code"] == 0
    assert [item["id"] for item in payload["data"]["items"]] == [own.id]
    assert payload["data"]["summary"]["project_count"] == 1
    assert payload["data"]["summary"]["chapter_count"] == 1
    assert "Private manuscript" not in str(payload)
    anonymous = (await client.get("/api/novel/overview")).json()
    assert anonymous["code"] == 401


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


@pytest.mark.asyncio
async def test_same_project_name_is_independent_between_teams(client: AsyncClient):
    team_a = await _create_team("Name scope A")
    team_b = await _create_team("Name scope B")
    await _create_member("name_alice", team_a)
    await _create_member("name_bob", team_b)
    await _create_member("name_carol", team_a)
    tokens = {name: await _login(client, name) for name in ("name_alice", "name_bob", "name_carol")}

    bodies = [
        (await client.post("/api/novel", json={"name": "同一本小说", "content": name}, headers=_auth(tokens[name]))).json()
        for name in ("name_alice", "name_bob", "name_carol")
    ]
    assert all(body["code"] == 0 for body in bodies)
    assert [body["data"]["name"] for body in bodies] == ["同一本小说", "同一本小说", "同一本小说 (2)"]
    own_ids = {bodies[0]["data"]["id"], bodies[2]["data"]["id"]}
    own = (await client.get("/api/novel", headers=_auth(tokens["name_alice"]))).json()
    assert {item["id"] for item in own["data"]["items"]} == own_ids
    foreign_id = bodies[1]["data"]["id"]
    for method in ("get", "patch", "delete"):
        kwargs = {"json": {"name": "试图修改"}} if method == "patch" else {}
        response = await getattr(client, method)(f"/api/novel/{foreign_id}", headers=_auth(tokens["name_alice"]), **kwargs)
        assert response.json()["code"] == 404
    assert await Novel.filter(id=foreign_id, team_id=team_b.id, name="同一本小说").exists()


@pytest.mark.asyncio
async def test_team_bootstrap_keeps_personal_projects_in_creator_scope(client: AsyncClient):
    team = await _create_team("Personal scope guard")
    owner = await User.create(username="personal_owner", password_hash=hash_password("password123"))
    personal = await _create_novel("重启同名项目", created_by=owner.id)
    shared = await _create_novel("重启同名项目", team=team)
    legacy = await _create_novel("历史无归属项目")
    personal_usage = await ModelUsageRecord.create(
        novel_id=personal.id, task_type=AiTaskTypeEnum.extraction.value,
        billing_type="text", model="test-model", cost=1.5, team_id=None, user_id=owner.id,
    )

    await ensure_team_schema()
    await ensure_team_schema()

    await personal.refresh_from_db()
    await shared.refresh_from_db()
    await legacy.refresh_from_db()
    await personal_usage.refresh_from_db()
    assert personal.team_id is None
    assert personal.created_by == owner.id
    assert shared.team_id == team.id
    assert legacy.team_id == team.id
    assert personal_usage.team_id is None
    assert personal_usage.user_id == owner.id
    assert float(personal_usage.cost) == 1.5


@pytest.mark.asyncio
async def test_personal_projects_alone_do_not_trigger_a_default_team(client: AsyncClient):
    owner = await User.create(username="personal_only", password_hash=hash_password("password123"))
    personal = await _create_novel("个人项目", created_by=owner.id)

    await ensure_team_schema()
    await ensure_team_schema()

    await personal.refresh_from_db()
    assert personal.team_id is None
    assert await Team.all().count() == 0
