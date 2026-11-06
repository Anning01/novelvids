"""Durable full-refund reservation and settlement, independent of HTTP handlers."""
import hashlib
from decimal import Decimal

from fastapi import HTTPException
from tortoise.timezone import now
from tortoise.transactions import in_transaction

from auth.models import BalanceTransaction, RechargeOrder, Team
from services.wechat_pay import WeChatPayError, wechat_pay_service


class RechargeRefundService:
    @staticmethod
    def reference(order: RechargeOrder) -> str:
        # Keep the same provider idempotency key across timeouts and process restarts.
        return "REF" + hashlib.sha256(order.out_trade_no.encode()).hexdigest()[:40]

    async def request(self, out_trade_no: str, operator_user_id: int | None, reason: str) -> RechargeOrder:
        async with in_transaction():
            order = await RechargeOrder.filter(out_trade_no=out_trade_no).select_for_update().first()
            if order is None:
                raise HTTPException(404, "充值订单不存在")
            if order.status == "refunded":
                raise HTTPException(400, "该订单已完成退款，不可重复退款")
            if order.status not in {"paid", "refunding"}:
                raise HTTPException(400, "仅已支付成功的订单支持退款")
            if order.status == "paid":
                team = await Team.filter(id=order.team_id).select_for_update().first()
                if team is None:
                    raise HTTPException(404, "充值目标团队不存在")
                if team.balance < order.amount:
                    raise HTTPException(400, "团队余额不足，不支持退款")
                team.balance -= order.amount
                await team.save(update_fields=["balance", "updated_at"])
                await BalanceTransaction.create(team=team, change_amount=-order.amount,
                    balance_after=team.balance, type="refund", operator_user_id=operator_user_id,
                    note=f"微信订单退款预留 (单号: {order.out_trade_no})")
                order.status = "refunding"
                order.refund_reason = reason or "管理员退款"
                await order.save(update_fields=["status", "refund_reason", "updated_at"])
        # The reservation survives a process crash or an ambiguous provider response.
        try:
            result = await wechat_pay_service.create_refund(out_trade_no=order.out_trade_no,
                out_refund_no=self.reference(order), amount_yuan=order.amount,
                total_yuan=order.amount, reason=order.refund_reason)
            await self.settle(order, result)
        except (WeChatPayError, ValueError):
            # Keep funds reserved; explicit sync queries the same refund before a retry.
            pass
        await order.refresh_from_db()
        return order

    async def sync(self, order: RechargeOrder) -> None:
        try:
            result = await wechat_pay_service.query_refund(self.reference(order))
            await self.settle(order, result)
        except (WeChatPayError, ValueError):
            pass
        await order.refresh_from_db()

    async def settle(self, order: RechargeOrder, result: dict) -> None:
        status = result.get("status")
        if status not in {"SUCCESS", "PROCESSING", "CLOSED", "ABNORMAL"}:
            raise ValueError("Invalid refund status")
        async with in_transaction():
            locked = await RechargeOrder.filter(id=order.id).select_for_update().first()
            if locked is None or locked.status != "refunding":
                return
            if result.get("refund_id"):
                locked.refund_id = result["refund_id"]
            if status == "SUCCESS":
                locked.status = "refunded"
                locked.refunded_at = now()
            elif status == "CLOSED":
                team = await Team.filter(id=locked.team_id).select_for_update().get()
                team.balance += Decimal(locked.amount)
                await team.save(update_fields=["balance", "updated_at"])
                await BalanceTransaction.create(team=team, change_amount=locked.amount,
                    balance_after=team.balance, type="adjustment",
                    note=f"微信退款关闭退回预留 (单号: {locked.out_trade_no})")
                locked.status = "refund_closed"
            # ABNORMAL still holds funds in WeChat's intermediate account.
            await locked.save(update_fields=["status", "refund_id", "refunded_at", "updated_at"])


recharge_refunds = RechargeRefundService()
