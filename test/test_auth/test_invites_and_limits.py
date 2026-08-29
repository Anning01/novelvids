"""第二阶段测试：邀请链接、成员禁用/限额/累计消耗、团队选择器作用域、人员上限。

仅在 AUTH_ENABLED=true 时运行。
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from auth.models import Team, TeamInvite, TeamMember, User
from auth.security import hash_password
from config import settings
from models.config import AiModelConfig
from models.novel import Novel
from services.ai_task_executor import ai_task_executor
from services.balance import top_up
from services.billing.recorder import record_ai_task_usage
from utils.enums import AiTaskTypeEnum, TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时功能未启用"
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


def _auth(token: str, team_id: int | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if team_id is not None:
        headers["X-Team-Id"] = str(team_id)
    return headers


async def _world(client: AsyncClient):
    team_a = await Team.create(name="二期A队")
    team_b = await Team.create(name="二期B队")
    admin = await _create_user("s2_admin")
    member_a = await _create_user("s2_member")
    await TeamMember.create(team=team_a, user=admin, role=TeamRoleEnum.admin.value)
    await TeamMember.create(team=team_a, user=member_a, role=TeamRoleEnum.creator.value)
    await TeamMember.create(team=team_b, user=member_a, role=TeamRoleEnum.creator.value)
    tokens = {
        "admin": await _login(client, "s2_admin"),
        "member": await _login(client, "s2_member"),
    }
    return {"team_a": team_a, "team_b": team_b, "member": member_a, "tokens": tokens}


# ---------------------------------------------------------------- 邀请链接


@pytest.mark.asyncio
async def test_invite_expires_in_24_hours(client):
    team = await Team.create(name="邀请队")
    admin = await _create_user("inv_admin")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    token = await _login(client, "inv_admin")

    response = await client.post("/api/team/invites", headers=_auth(token))
    invite = await TeamInvite.first()
    assert response.json()["code"] == 0
    assert datetime.fromisoformat(response.json()["data"]["expires_at"])
    ttl = (invite.expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 23 * 3600 < ttl <= 24 * 3600


@pytest.mark.asyncio
async def test_expired_invite_rejected(client):
    team = await Team.create(name="过期队")
    admin = await _create_user("exp_admin")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    token = await _login(client, "exp_admin")
    created = await client.post("/api/team/invites", headers=_auth(token))
    invite_token = created.json()["data"]["token"]

    invite = await TeamInvite.get(token=invite_token)
    invite.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await invite.save(update_fields=["expires_at", "updated_at"])

    info = await client.get(f"/api/team/invites/{invite_token}")
    assert info.json()["code"] == 404

    member = await _create_user("exp_member")
    member_token = await _login(client, "exp_member")
    joined = await client.post(
        f"/api/team/invites/{invite_token}/join", headers=_auth(member_token)
    )
    assert joined.json()["code"] == 404


@pytest.mark.asyncio
async def test_existing_user_joins_via_invite(client):
    world = await _world(client)
    response = await client.post(
        "/api/team/invites", headers=_auth(world["tokens"]["admin"])
    )
    token = response.json()["data"]["token"]

    outsider = await _create_user("outsider")
    outsider_token = await _login(client, "outsider")
    joined = await client.post(
        f"/api/team/invites/{token}/join", headers=_auth(outsider_token)
    )
    assert joined.json()["code"] == 0, joined.text
    assert joined.json()["data"]["team_id"] == world["team_a"].id

    # 重复加入被拒
    again = await client.post(
        f"/api/team/invites/{token}/join", headers=_auth(outsider_token)
    )
    assert again.json()["code"] == 400


@pytest.mark.asyncio
async def test_member_limit_enforced_on_join_and_register(client):
    team = await Team.create(name="满员队", member_limit=1)
    admin = await _create_user("full_admin")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    admin_token = await _login(client, "full_admin")
    invite = await client.post("/api/team/invites", headers=_auth(admin_token))
    token = invite.json()["data"]["token"]

    newcomer = await _create_user("newcomer")
    newcomer_token = await _login(client, "newcomer")
    joined = await client.post(
        f"/api/team/invites/{token}/join", headers=_auth(newcomer_token)
    )
    assert joined.json()["code"] == 403

    registered = await client.post(
        "/api/auth/register",
        json={"username": "reg_new", "password": "reg-pass-123", "invite_token": token},
    )
    assert registered.json()["code"] == 403


# ---------------------------------------------------------------- 成员禁用 / 限额 / 累计消耗


@pytest.mark.asyncio
async def test_admin_can_disable_and_re_enable_member(client):
    world = await _world(client)
    member_id = world["member"].id

    disabled = await client.patch(
        f"/api/team/members/{member_id}",
        json={"status": 0},
        headers=_auth(world["tokens"]["admin"]),
    )
    assert disabled.json()["code"] == 0
    assert disabled.json()["data"]["status"] == 0

    # 被禁用成员无法访问该团队（X-Team-Id 指向 A 队）
    denied = await client.get(
        "/api/novel", headers=_auth(world["tokens"]["member"], team_id=world["team_a"].id)
    )
    assert denied.json()["code"] == 403

    # 其他团队不受影响
    other = await client.get(
        "/api/novel", headers=_auth(world["tokens"]["member"], team_id=world["team_b"].id)
    )
    assert other.json()["code"] == 0

    enabled = await client.patch(
        f"/api/team/members/{member_id}",
        json={"status": 1},
        headers=_auth(world["tokens"]["admin"]),
    )
    assert enabled.json()["data"]["status"] == 1


@pytest.mark.asyncio
async def test_admin_sets_member_cost_limit(client):
    world = await _world(client)
    member_id = world["member"].id

    set_limit = await client.put(
        f"/api/team/members/{member_id}/limit",
        json={"cost_limit": "10.5"},
        headers=_auth(world["tokens"]["admin"]),
    )
    assert set_limit.json()["code"] == 0
    assert Decimal(set_limit.json()["data"]["cost_limit"]) == Decimal("10.500000")

    # null 取消限额
    cleared = await client.put(
        f"/api/team/members/{member_id}/limit",
        json={"cost_limit": None},
        headers=_auth(world["tokens"]["admin"]),
    )
    assert cleared.json()["data"]["cost_limit"] is None


@pytest.mark.asyncio
async def test_member_cost_limit_blocks_task_submit(client):
    world = await _world(client)
    member_id = world["member"].id
    await top_up(world["team_a"].id, Decimal("100"))
    await TeamMember.filter(team_id=world["team_a"].id, user_id=member_id).update(
        cost_limit=Decimal("5"), total_cost=Decimal("5")
    )

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await ai_task_executor.submit(
            AiTaskTypeEnum.extraction,
            {"novel_id": 1, "team_id": world["team_a"].id, "user_id": member_id},
        )
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_usage_record_accumulates_member_total_cost(client):
    """计费落点 → 团队扣费 + 成员累计消耗同步增加。"""
    world = await _world(client)
    await top_up(world["team_a"].id, Decimal("100"))
    novel = await Novel.create(name="消耗项目", author="x", team_id=world["team_a"].id)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="计费文本",
        base_url="https://x",
        api_key="k",
        model="m",
        is_active=True,
        pricing={
            "type": "text",
            "currency": "CNY",
            "input_price_per_1m": 10_000,
            "output_price_per_1m": 20_000,
        },
    )
    task = await ai_task_executor.submit(
        AiTaskTypeEnum.extraction,
        {
            "novel_id": novel.id,
            "team_id": world["team_a"].id,
            "user_id": world["member"].id,
            "model_config_id": config.id,
        },
    )
    await record_ai_task_usage(
        task, result={"token_usage": {"prompt_tokens": 1000, "completion_tokens": 500}}
    )

    membership = await TeamMember.get(
        team_id=world["team_a"].id, user_id=world["member"].id
    )
    # 10_000/1_000_000*1000 + 20_000/1_000_000*500 = 10 + 10 = 20 元
    assert membership.total_cost == Decimal("20.000000")
    team = await Team.get(id=world["team_a"].id)
    assert team.balance == Decimal("80.000000")

    listing = await client.get(
        "/api/team/members", headers=_auth(world["tokens"]["admin"])
    )
    member_row = next(
        item for item in listing.json()["data"]["items"] if item["user_id"] == world["member"].id
    )
    assert Decimal(member_row["total_cost"]) == Decimal("20.000000")


# ---------------------------------------------------------------- 团队选择器作用域


@pytest.mark.asyncio
async def test_x_team_id_scopes_data(client):
    """侧边栏选择器（X-Team-Id）决定数据作用域；非法团队 403。"""
    world = await _world(client)
    await Novel.create(name="A队项目", author="x", team_id=world["team_a"].id)
    await Novel.create(name="B队项目", author="x", team_id=world["team_b"].id)

    member_token = world["tokens"]["member"]
    in_a = await client.get(
        "/api/novel", headers=_auth(member_token, team_id=world["team_a"].id)
    )
    names_a = [item["name"] for item in in_a.json()["data"]["items"]]
    assert names_a == ["A队项目"]

    in_b = await client.get(
        "/api/novel", headers=_auth(member_token, team_id=world["team_b"].id)
    )
    names_b = [item["name"] for item in in_b.json()["data"]["items"]]
    assert names_b == ["B队项目"]

    bad_team = await client.get(
        "/api/novel", headers=_auth(member_token, team_id=99999)
    )
    assert bad_team.json()["code"] == 403


# ---------------------------------------------------------------- 团队人员上限


@pytest.mark.asyncio
async def test_team_created_with_member_limit(client):
    boss = await _create_user("limit_boss", super_admin=True)
    token = await _login(client, "limit_boss")
    member = await _create_user("limit_member")
    created = await client.post(
        "/api/team/teams",
        json={"name": "限员队", "member_limit": 3, "owner_user_id": member.id},
        headers=_auth(token),
    )
    assert created.json()["code"] == 0, created.text
    assert created.json()["data"]["member_limit"] == 3
    assert datetime.fromisoformat(created.json()["data"]["created_at"])
    assert datetime.fromisoformat(created.json()["data"]["updated_at"])

    updated = await client.patch(
        f"/api/team/teams/{created.json()['data']['id']}",
        json={"member_limit": 5},
        headers=_auth(token),
    )
    assert updated.json()["data"]["member_limit"] == 5
