"""One new admission is safe only after a recorded upstream 429 was definitively rejected."""
from uuid import UUID, uuid5

import httpx

from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from schemas.platform_billing import PlatformReceiptOut


async def confirmed_rejection(config, parent_id, key):
    if getattr(config, "api_protocol", None) != "novelvids":
        return False
    child = uuid5(UUID(str(parent_id)), key)
    usage_ids = await ModelUsageRecord.filter(ai_task_id=child, model_config_id=config.id).values_list('id', flat=True)
    rows = await StudioCall.filter(usage_record_id__in=usage_ids).limit(2)
    if len(rows) != 1:
        return False
    row = rows[0]
    if not row.platform_request_id or row.base_url != config.base_url.rstrip("/"):
        return False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
            response = await client.get(f"{row.base_url}/requests/{row.platform_request_id}",
                                        headers={"Authorization": f"Bearer {config.api_key}"})
            response.raise_for_status()
            receipt = PlatformReceiptOut.model_validate(response.json())
    except (httpx.HTTPError, ValueError):
        return False
    return (receipt.id == row.platform_request_id and receipt.model == config.model
            and receipt.status == "rejected" and receipt.settlement.status == "not_charged"
            and receipt.settlement.amount in (None, 0))


async def run_admitted(call, config, params, receipt_name):
    try:
        return await call(None)
    except Exception as exc:
        if getattr(exc, "error_code", None) != "REMAKE_ANALYSIS_RATE_LIMITED":
            raise
        key = f"model:remake:{receipt_name}:1"
        if not await confirmed_rejection(config, params["task_id"], key):
            raise
    # Separate at-most-once operation and platform request key; the old receipt remains rejected.
    return await call("1-readmit")
