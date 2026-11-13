from fastapi import HTTPException

from auth.models import PlatformCallReceipt
from models.usage_record import ModelUsageRecord
from schemas.platform_billing import PlatformReceiptOut, PlatformSettlement
from services.platform.catalog import public_tariff
from services.platform.calls import digest


async def call_receipt(request_id, ctx, *, by_key=False) -> PlatformReceiptOut:
    identity = {"dedup_key": digest([ctx.team_id, ctx.user.id, str(request_id)])} if by_key else {"public_id": request_id}
    row = await PlatformCallReceipt.get_or_none(**identity, team_id=ctx.team_id, user_id=ctx.user.id)
    if row is None:
        raise HTTPException(404, "请求不存在")
    settlement = PlatformSettlement(status="review" if row.state == "review" else
        "not_charged" if row.state == "rejected" else "pending")
    if row.state == "completed" and row.usage_record_id is not None:
        record = await ModelUsageRecord.get_or_none(id=row.usage_record_id, team_id=row.team_id, user_id=row.user_id)
        if record is not None:
            settlement = PlatformSettlement(status="settled", amount=record.cost, currency=record.currency)
    return PlatformReceiptOut(id=row.public_id, model=f"nv-{row.model_config_id}", status=row.state,
        usage=row.usage, settlement=settlement, pricing=public_tariff(row.pricing))
