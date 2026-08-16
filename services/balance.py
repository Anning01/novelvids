"""团队余额服务：充值、消费、欠费预检与流水。

策略（D3）：任务提交前预检余额 > 0；任务完成后按计费流水金额原子扣减；
并发下允许透支为负（欠费团队在管理端标红，禁止新任务）。
计费/扣减是旁路副作用：消费失败只记日志，绝不打断生成主流程。
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from auth.models import BalanceTransaction, Team, TeamMember
from config import settings

logger = logging.getLogger(__name__)

_CENT = Decimal("0.000001")


def _money(value) -> Decimal:
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0")


async def get_balance(team_id: int) -> Decimal:
    team = await Team.get_or_none(id=team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    return team.balance


async def ensure_solvent(
    team_id: int | None, user_id: int | None = None
) -> None:
    """任务提交前预检：欠费团队禁止新任务；成员超出个人消费限额也拦截。

    关闭开关/超管（无团队）跳过。
    """
    if not settings.AUTH_ENABLED or team_id is None:
        return
    team = await Team.get_or_none(id=team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if team.balance <= 0:
        raise HTTPException(
            status_code=402, detail="团队余额不足，请联系团队管理员充值"
        )
    if user_id is not None:
        membership = await TeamMember.get_or_none(team_id=team_id, user_id=user_id)
        if membership is not None and membership.cost_limit is not None:
            if membership.total_cost >= membership.cost_limit:
                raise HTTPException(
                    status_code=402,
                    detail="你已达到个人消费限额，请联系团队管理员调整",
                )


async def accumulate_member_cost(
    team_id: int, user_id: int | None, cost
) -> None:
    """累计成员历史消耗金额（旁路副作用，失败仅记日志）。"""
    if user_id is None:
        return
    try:
        cost_dec = _money(cost)
        if cost_dec <= 0:
            return
        updated = await TeamMember.filter(team_id=team_id, user_id=user_id).update(
            total_cost=F("total_cost") + cost_dec
        )
        if updated == 0:
            logger.warning(
                "member cost accumulate skipped: team_id=%s user_id=%s", team_id, user_id
            )
    except Exception:
        logger.exception(
            "member cost accumulate failed team_id=%s user_id=%s", team_id, user_id
        )


async def top_up(
    team_id: int,
    amount: Decimal,
    operator_user_id: int | None = None,
    note: str = "",
) -> Decimal:
    """超管充值；事务内加锁更新余额并落流水。"""
    amount_dec = _money(amount)
    if amount_dec <= 0:
        raise HTTPException(status_code=400, detail="充值金额必须为正数")
    async with in_transaction():
        team = await Team.filter(id=team_id).select_for_update().first()
        if team is None:
            raise HTTPException(status_code=404, detail="团队不存在")
        team.balance = _money(team.balance + amount_dec)
        await team.save(update_fields=["balance", "updated_at"])
        await BalanceTransaction.create(
            team=team,
            change_amount=amount_dec,
            balance_after=team.balance,
            type="topup",
            operator_user_id=operator_user_id,
            note=note or "余额充值",
        )
    return team.balance


async def consume(
    team_id: int,
    cost,
    usage_record_id: int | None = None,
) -> Decimal | None:
    """任务完成后按实际成本扣减；允许透支为负。失败仅记日志，不抛异常。"""
    try:
        cost_dec = _money(cost)
        if cost_dec <= 0:
            return None
        async with in_transaction():
            team = await Team.filter(id=team_id).select_for_update().first()
            if team is None:
                return None
            team.balance = _money(team.balance - cost_dec)
            await team.save(update_fields=["balance", "updated_at"])
            await BalanceTransaction.create(
                team=team,
                change_amount=-cost_dec,
                balance_after=team.balance,
                type="consume",
                usage_record_id=usage_record_id,
                note="AI 调用扣费",
            )
        return team.balance
    except Exception:
        logger.exception("balance consume failed team_id=%s", team_id)
        return None


async def list_transactions(
    team_id: int, page: int, page_size: int
) -> dict:
    """团队余额流水（分页，倒序）。"""
    query = BalanceTransaction.filter(team_id=team_id)
    total = await query.count()
    items = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    pages = (total + page_size - 1) // page_size if total else 0
    return {
        "items": items,
        "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
    }
