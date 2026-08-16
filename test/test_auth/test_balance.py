"""团队余额测试：充值、消费扣减、透支、欠费拦截、流水归属。

仅在 AUTH_ENABLED=true 时运行。
"""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from auth.models import BalanceTransaction, Team, TeamMember, User
from auth.security import hash_password
from config import settings
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services import balance
from services.ai_task_executor import ai_task_executor
from services.billing.recorder import record_ai_task_usage
from utils.enums import AiTaskTypeEnum, TeamRoleEnum

pytestmark = pytest.mark.skipif(
    not settings.AUTH_ENABLED, reason="AUTH_ENABLED=false 时余额功能未启用"
)

PASSWORD = "password123"


async def _create_user(username: str, *, super_admin: bool = False) -> User:
    return await User.create(
        username=username,
        nickname=username,
        password_hash=hash_password(PASSWORD),
        is_super_admin=super_admin,
    )


async def _login(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.json()["code"] == 0, response.text
    return response.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- 服务层


@pytest.mark.asyncio
async def test_top_up_records_transaction():
    team = await Team.create(name="充值队")
    result = await balance.top_up(team.id, Decimal("100"), operator_user_id=1, note="首充")
    assert result == Decimal("100.000000")

    transactions = await BalanceTransaction.filter(team=team).all()
    assert len(transactions) == 1
    assert transactions[0].type == "topup"
    assert transactions[0].change_amount == Decimal("100.000000")
    assert transactions[0].balance_after == Decimal("100.000000")
    assert transactions[0].operator_user_id == 1


@pytest.mark.asyncio
async def test_top_up_rejects_non_positive():
    team = await Team.create(name="负数队")
    with pytest.raises(HTTPException) as exc:
        await balance.top_up(team.id, Decimal("-5"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_consume_deducts_and_allows_overdraft():
    team = await Team.create(name="透支队")
    await balance.top_up(team.id, Decimal("10"))

    result = await balance.consume(team.id, Decimal("4.5"), usage_record_id=None)
    assert result == Decimal("5.500000")

    # 透支：扣减后为负也允许（D3）
    overdraft = await balance.consume(team.id, Decimal("20"), usage_record_id=None)
    assert overdraft == Decimal("-14.500000")

    transactions = await BalanceTransaction.filter(team=team, type="consume").all()
    assert len(transactions) == 2
    assert transactions[1].balance_after == Decimal("-14.500000")


@pytest.mark.asyncio
async def test_ensure_solvent_blocks_insolvent_team():
    team = await Team.create(name="欠费队")
    with pytest.raises(HTTPException) as exc:
        await balance.ensure_solvent(team.id)
    assert exc.value.status_code == 402

    await balance.top_up(team.id, Decimal("1"))
    await balance.ensure_solvent(team.id)  # 不抛异常


@pytest.mark.asyncio
async def test_submit_blocked_when_team_insolvent():
    team = await Team.create(name="拦截队")
    with pytest.raises(HTTPException) as exc:
        await ai_task_executor.submit(
            AiTaskTypeEnum.extraction, {"novel_id": 1, "team_id": team.id}
        )
    assert exc.value.status_code == 402

    await balance.top_up(team.id, Decimal("5"))
    task = await ai_task_executor.submit(
        AiTaskTypeEnum.extraction, {"novel_id": 1, "team_id": team.id}
    )
    assert task is not None


@pytest.mark.asyncio
async def test_record_ai_task_usage_attributes_and_deducts():
    """计费落点写入 team_id/user_id 并按成本扣减余额。"""
    team = await Team.create(name="归属队")
    await balance.top_up(team.id, Decimal("100"))
    novel = await Novel.create(name="归属项目", author="x", team_id=team.id)
    task = await ai_task_executor.submit(
        AiTaskTypeEnum.extraction,
        {
            "novel_id": novel.id,
            "team_id": team.id,
            "user_id": 42,
            "model_config_id": None,
        },
    )
    await record_ai_task_usage(
        task,
        result={"token_usage": {"prompt_tokens": 1000, "completion_tokens": 500}},
    )
    record = await ModelUsageRecord.first()
    assert record.team_id == team.id
    assert record.user_id == 42

    team = await Team.get(id=team.id)
    # 无定价时成本为 0，余额不变（扣除为 0 不落流水）
    assert team.balance == Decimal("100.000000")


# ---------------------------------------------------------------- API 层


@pytest.mark.asyncio
async def test_super_admin_can_top_up_via_api(client: AsyncClient):
    team = await Team.create(name="API充值队")
    boss = await _create_user("bal_boss", super_admin=True)
    token = await _login(client, "bal_boss")

    response = await client.post(
        "/api/team/balance/topup",
        json={"team_id": team.id, "amount": "50", "note": "运营充值"},
        headers=_auth(token),
    )
    assert response.json()["code"] == 0, response.text
    assert Decimal(response.json()["data"]["balance"]) == Decimal("50.000000")


@pytest.mark.asyncio
async def test_team_admin_sees_own_balance(client: AsyncClient):
    team = await Team.create(name="管理员队")
    await balance.top_up(team.id, Decimal("30"))
    admin = await _create_user("bal_admin")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    token = await _login(client, "bal_admin")

    response = await client.get("/api/team/balance", headers=_auth(token))
    assert response.json()["code"] == 0
    assert Decimal(response.json()["data"]["balance"]) == Decimal("30.000000")


@pytest.mark.asyncio
async def test_team_admin_cannot_top_up(client: AsyncClient):
    team = await Team.create(name="无权充值队")
    admin = await _create_user("bal_admin2")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    token = await _login(client, "bal_admin2")

    response = await client.post(
        "/api/team/balance/topup",
        json={"team_id": team.id, "amount": "10"},
        headers=_auth(token),
    )
    assert response.json()["code"] == 403


@pytest.mark.asyncio
async def test_transactions_list(client: AsyncClient):
    team = await Team.create(name="流水队")
    await balance.top_up(team.id, Decimal("10"))
    await balance.consume(team.id, Decimal("2"), usage_record_id=None)
    admin = await _create_user("bal_admin3")
    await TeamMember.create(team=team, user=admin, role=TeamRoleEnum.admin.value)
    token = await _login(client, "bal_admin3")

    response = await client.get(
        "/api/team/balance/transactions", headers=_auth(token)
    )
    data = response.json()["data"]
    assert data["pagination"]["total"] == 2
    types = [item["type"] for item in data["items"]]
    assert types == ["consume", "topup"]  # 倒序


@pytest.mark.asyncio
async def test_creator_cannot_read_balance(client: AsyncClient):
    team = await Team.create(name="创作者队")
    creator = await _create_user("bal_creator")
    await TeamMember.create(team=team, user=creator, role=TeamRoleEnum.creator.value)
    token = await _login(client, "bal_creator")

    response = await client.get("/api/team/balance", headers=_auth(token))
    assert response.json()["code"] == 403
