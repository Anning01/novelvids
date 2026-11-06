"""Payment safety regressions discovered during release review."""
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from auth.models import BalanceTransaction, RechargeOrder, Team, User
from config import settings
from controllers.team import team_controller
from services.wechat_pay import wechat_pay_service
from test.test_auth.test_wechat_pay_recharge import mock_wechat_keys

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not settings.AUTH_ENABLED, reason="requires auth")]


async def test_payment_replay_cannot_credit_a_refunded_order(mock_wechat_keys):
    team = await Team.create(name="refunded-replay", balance=Decimal("100"))
    user = await User.create(username="refunded-replay")
    order = await RechargeOrder.create(out_trade_no="REC_REPLAY", team=team,
        user_id=user.id, amount=Decimal("50"), status="refunded", transaction_id="WX_ORIGINAL")

    credited = await team_controller._finish_recharge(order, "WX_ORIGINAL")

    assert credited is False
    await order.refresh_from_db()
    await team.refresh_from_db()
    assert order.status == "refunded"
    assert team.balance == Decimal("100")
    assert not await BalanceTransaction.filter(team=team).exists()


async def test_refund_processing_is_not_reported_as_completed(mock_wechat_keys, monkeypatch):
    team = await Team.create(name="refund-processing", balance=Decimal("100"))
    user = await User.create(username="refund-processing")
    order = await RechargeOrder.create(out_trade_no="REC_PROCESSING", team=team,
        user_id=user.id, amount=Decimal("50"), status="paid", transaction_id="WX_ORIGINAL")
    monkeypatch.setattr(wechat_pay_service, "create_refund", AsyncMock(return_value={
        "refund_id": "WX_REFUND", "status": "PROCESSING"}))

    await team_controller.refund_recharge(order.out_trade_no)

    await order.refresh_from_db()
    assert order.status != "refunded"
    assert order.refunded_at is None


async def test_callback_verification_requires_a_platform_public_key(mock_wechat_keys, monkeypatch):
    import time
    monkeypatch.setattr(wechat_pay_service, "_public_key", None)
    assert wechat_pay_service.verify_signature(str(int(time.time())), "nonce", "{}", "invalid") is False


async def test_concurrent_refunds_reserve_once_and_reuse_provider_key(mock_wechat_keys, monkeypatch):
    import asyncio
    team = await Team.create(name="concurrent-refund", balance=Decimal("150"))
    user = await User.create(username="concurrent-refund")
    order = await RechargeOrder.create(out_trade_no="REC_CONCURRENT", team=team,
        user_id=user.id, amount=Decimal("50"), status="paid")
    request = AsyncMock(return_value={"refund_id": "WX_R", "status": "PROCESSING"})
    monkeypatch.setattr(wechat_pay_service, "create_refund", request)
    await asyncio.gather(*(team_controller.refund_recharge(order.out_trade_no) for _ in range(2)))
    await team.refresh_from_db()
    assert team.balance == Decimal("100")
    assert await BalanceTransaction.filter(team=team, type="refund").count() == 1
    assert len({call.kwargs['out_refund_no'] for call in request.await_args_list}) == 1


async def test_unknown_refund_survives_retry_and_closed_refund_restores_once(mock_wechat_keys, monkeypatch):
    from services.wechat_pay import WeChatPayError
    team = await Team.create(name="unknown-refund", balance=Decimal("100"))
    user = await User.create(username="unknown-refund")
    order = await RechargeOrder.create(out_trade_no="REC_UNKNOWN", team=team,
        user_id=user.id, amount=Decimal("50"), status="paid")
    request = AsyncMock(side_effect=[WeChatPayError("timeout"), {"refund_id": "WX_R", "status": "PROCESSING"}])
    monkeypatch.setattr(wechat_pay_service, "create_refund", request)
    for _ in range(2):
        result = await team_controller.refund_recharge(order.out_trade_no)
        assert result.status == "refunding"
    assert request.await_args_list[0].kwargs['out_refund_no'] == request.await_args_list[1].kwargs['out_refund_no']
    monkeypatch.setattr(wechat_pay_service, "query_refund", AsyncMock(return_value={"status": "CLOSED"}))
    from services.recharge_refunds import recharge_refunds
    await recharge_refunds.sync(result)
    await recharge_refunds.sync(result)
    await team.refresh_from_db()
    assert team.balance == Decimal("100")
    assert result.status == "refund_closed"
    assert await BalanceTransaction.filter(team=team, type="refund").count() == 1
    assert await BalanceTransaction.filter(team=team, type="adjustment").count() == 1


async def test_processing_refund_syncs_to_success_without_another_deduction(mock_wechat_keys, monkeypatch):
    team = await Team.create(name="refund-settlement", balance=Decimal("100"))
    user = await User.create(username="refund-settlement")
    order = await RechargeOrder.create(out_trade_no="REC_SETTLEMENT", team=team,
        user_id=user.id, amount=Decimal("50"), status="paid")
    monkeypatch.setattr(wechat_pay_service, "create_refund", AsyncMock(return_value={"status": "PROCESSING"}))
    await team_controller.refund_recharge(order.out_trade_no)
    monkeypatch.setattr(wechat_pay_service, "query_refund", AsyncMock(return_value={"status": "SUCCESS", "refund_id": "WX_R"}))
    result, _ = await team_controller.query_recharge(order.out_trade_no, user.id)
    assert result.status == "refunded" and result.refunded_at is not None
    await team.refresh_from_db()
    assert team.balance == Decimal("50")
    assert await BalanceTransaction.filter(team=team).count() == 1


async def test_payment_query_cannot_credit_mismatched_amount(mock_wechat_keys, monkeypatch):
    team = await Team.create(name="bad-query", balance=Decimal("100"))
    user = await User.create(username="bad-query")
    order = await RechargeOrder.create(out_trade_no="REC_BAD_QUERY", team=team,
        user_id=user.id, amount=Decimal("50"), status="pending")
    monkeypatch.setattr(wechat_pay_service, "query_order", AsyncMock(return_value={
        "trade_state": "SUCCESS", "transaction_id": "WX", "out_trade_no": order.out_trade_no,
        "mchid": mock_wechat_keys.mch_id, "appid": mock_wechat_keys.app_id,
        "amount": {"total": 1, "currency": "CNY"}}))
    result, _ = await team_controller.query_recharge(order.out_trade_no, user.id)
    assert result.status == "pending"
    await team.refresh_from_db()
    assert team.balance == Decimal("100")
