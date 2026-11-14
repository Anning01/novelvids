"""Durable platform call attribution and local settlement from authenticated receipts."""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import logging
from uuid import UUID, uuid4
from urllib.parse import quote

import httpx
from httpx import AsyncClient
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from config import settings
from models.ai_task import AiTask
from models.config import AiModelConfig
from models.studio_call import StudioCall
from models.usage_record import ModelUsageRecord
from schemas.platform_billing import PlatformReceiptOut
from services.balance import ensure_solvent
from services.billing.pricing import pixel_receipt_cost, compute_image_cost, compute_input_image_cost, compute_text_cost, compute_video_cost


active_model_call = ContextVar("platform_model_call", default=None)
logger = logging.getLogger(__name__)


def is_platform_model(config):
    return config.api_protocol == "novelvids" or (config.model.startswith("nv-") and config.api_key.startswith("nv_"))


async def begin_platform_call(config, *, billing_type, task_id=None, video_id=None, message_id=None, request_key=None):
    task = await AiTask.get_or_none(id=task_id) if task_id else None
    if video_id is not None:
        from models.video import Video
        owner = (await Video.get(id=video_id)).metadata
    else:
        owner = task.request_params if task else {}
    await ensure_solvent(owner.get("team_id"), owner.get("user_id"))
    async with in_transaction() as db:
        if request_key:
            existing = await StudioCall.get_or_none(request_key=request_key).using_db(db)
            if existing is not None:
                return existing
        record = await ModelUsageRecord.create(using_db=db,
            novel_id=owner.get("novel_id", 0), task_type=task.task_type if task else 4 if billing_type == "video" else 2,
            billing_type=billing_type, ai_task_id=task.id if task else None, video_id=video_id,
            model_config_id=config.id, model_name=config.name, model=config.model,
            cost_source="platform_key", status=2, settlement_status="pending",
            team_id=owner.get("team_id"), user_id=owner.get("user_id"))
        return await StudioCall.create(using_db=db, request_key=request_key or uuid4(), usage_record_id=record.id,
            message_id=message_id, model_config_id=config.id, base_url=config.base_url.rstrip("/"),
            billing_mode="team", multiplier=1, local_pricing=config.pricing or {},
            next_check_at=datetime.now(timezone.utc) + timedelta(seconds=30))


async def capture_platform_response(row, response):
    await ModelUsageRecord.filter(id=row.usage_record_id, billing_type="image").update(
        duration_seconds=max(0, (datetime.now(timezone.utc) - row.created_at).total_seconds()))
    value = response.headers.get("X-Cat-Request-Id") or response.headers.get("X-Novelvids-Request-Id")
    if value:
        try:
            request_id = UUID(value)
        except ValueError:
            return None
        await StudioCall.filter(id=row.id).update(platform_request_id=request_id)
        return request_id
    if response.headers.get("X-Request-Id"):
        # Provider trace (or legacy unlabelled receipt): reconcile using our original request key.
        return None
    if response.status_code in {400, 401, 402, 403, 404, 413, 422}:
        async with in_transaction() as db:
            rejected = await StudioCall.filter(id=row.id, state="pending", platform_request_id=None).using_db(db).update(state="rejected")
            if rejected:
                await ModelUsageRecord.filter(id=row.usage_record_id).using_db(db).update(
                    platform_cost=0, local_charge=0, settlement_status="settled", status=4)
    return None


async def begin_platform_image(base_url, model, api_key):
    from services.ai_task_executor import current_task_id
    task_id = current_task_id.get()
    if task_id is None or settings.DEPLOYMENT_ROLE != "studio":
        return None
    candidates = await AiModelConfig.filter(base_url=base_url, model=model, api_protocol="novelvids")
    config = next((row for row in candidates if row.api_key == api_key), None)
    if config is None:
        raise ValueError("Platform image model configuration is unavailable")
    return await begin_platform_call(config, billing_type="image", task_id=task_id)


def platform_text_client(config):
    from services.remake.capacity_transport import PlatformCapacityTransport
    async def before_request(request):
        if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
            return
        active = active_model_call.get()
        if active is None:
            raise ValueError("Platform text requests require an attributed call")
        message, call = active
        row = await begin_platform_call(config, billing_type="text", task_id=message.task_id, message_id=message.id)
        request.headers["Idempotency-Key"] = str(row.request_key)
        request.extensions["studio_call_id"] = row.id
        call["studio_call_id"] = row.id

    async def after_response(response):
        row_id = response.request.extensions.get("studio_call_id")
        if row_id is None:
            return
        request_id = await capture_platform_response(await StudioCall.get(id=row_id), response)
        active = active_model_call.get()
        if active and response.status_code == 402:
            active[1]["platform_balance_insufficient"] = True
        if request_id and active:
            active[1]["platform_request_id"] = str(request_id)

    return AsyncClient(timeout=None, follow_redirects=False, trust_env=False, transport=PlatformCapacityTransport(trust_env=False),
        event_hooks={"request": [before_request], "response": [after_response]})


async def finish_model_call(call, *, completed, usage, duration):
    row_id = call.get("studio_call_id")
    if row_id is None:
        return
    row = await StudioCall.get(id=row_id)
    measured = {**(usage or {}), "requests": 1, "cache_usage_reported": call.get("cache_usage_reported", False)}
    if call.get("phase") == "summary":
        measured.update(summary_requests=1, summary_input_tokens=measured.get("input_tokens", 0),
            summary_output_tokens=measured.get("output_tokens", 0))
    await ModelUsageRecord.filter(id=row.usage_record_id).update(status=3 if completed else 4, duration_seconds=duration)
    await ModelUsageRecord.filter(id=row.usage_record_id, settlement_status__in=["pending", "review"]).update(usage=measured)


async def settle_platform_call(row_id: int, receipt: PlatformReceiptOut) -> None:
    async with in_transaction() as db:
        query = StudioCall.filter(id=row_id).using_db(db)
        await query.update(state=F("state"))
        row = await query.get()
        if row.state in {"settled", "rejected"}:
            return
        if receipt.id != row.platform_request_id:
            raise ValueError("Settlement request does not match the saved platform request")
        ledger = await ModelUsageRecord.get(id=row.usage_record_id).using_db(db)
        if ledger.model.startswith("nv-") and receipt.model != ledger.model:
            raise ValueError("Settlement model does not match the saved platform model")
        status = receipt.settlement.status
        if status not in {"settled", "not_charged"}:
            await ModelUsageRecord.filter(id=ledger.id).using_db(db).update(
                settlement_status="review" if status == "review" else "pending")
            return
        amount = Decimal(0) if status == "not_charged" else receipt.settlement.amount
        if amount is None or receipt.settlement.currency != "CNY":
            raise ValueError("Platform receipt has no supported settled amount")
        pricing = row.local_pricing
        local_cost = Decimal(0)
        if status == "settled":
            usage = receipt.usage or {}
            if pricing is None:
                # In-flight calls keep the charging rule captured before the switch.
                if row.billing_mode == "team":
                    local_cost = (amount * row.multiplier).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            elif ledger.billing_type == "text":
                local_cost = compute_text_cost(usage, pricing)
            elif ledger.billing_type == "image" and pricing.get("billing_unit") == "pixel_tier":
                try:
                    local_cost = pixel_receipt_cost(usage, pricing)
                except ValueError:
                    await ModelUsageRecord.filter(id=ledger.id).using_db(db).update(
                        settlement_status="review", platform_cost=amount)
                    return
            elif ledger.billing_type == "image":
                local_cost = compute_image_cost(usage.get("image_count", 0), usage.get("clarity"), pricing)
                local_cost += compute_input_image_cost(usage.get("input_image_count", 0), pricing)
            elif ledger.billing_type == "video":
                local_cost = compute_video_cost(usage.get("seconds", 0), usage.get("resolution"), pricing,
                    usage.get("input_video_seconds", 0), usage.get("has_video_reference", False), usage.get("input_image_count", 0))
        charge = local_cost if ledger.team_id is not None else Decimal(0)
        if charge:
            from services.balance import consume, accumulate_member_cost
            await consume(ledger.team_id, charge, usage_record_id=ledger.id, strict=True)
            await accumulate_member_cost(ledger.team_id, ledger.user_id, charge, strict=True)
        ledger.cost = amount if pricing is None else local_cost
        ledger.platform_cost = amount
        ledger.local_charge = charge
        ledger.pricing_snapshot = receipt.pricing if pricing is None else pricing
        ledger.currency = receipt.settlement.currency
        ledger.settlement_status = "settled"
        ledger.usage = {**ledger.usage, **(receipt.usage or {}), "platform_request_id": str(receipt.id)}
        await ledger.save(using_db=db, update_fields=["cost", "platform_cost", "local_charge", "pricing_snapshot",
            "currency", "settlement_status", "usage", "updated_at"])
        await query.update(state="settled" if status == "settled" else "rejected")


async def reconcile_platform_calls() -> None:
    now = datetime.now(timezone.utc)
    candidates = await StudioCall.filter(state="pending", next_check_at__lte=now).order_by("next_check_at", "id").limit(50)
    async with AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
        for row in candidates:
            if not await StudioCall.filter(id=row.id, state="pending", next_check_at__lte=now).update(next_check_at=now + timedelta(seconds=30)):
                continue
            config = await AiModelConfig.get_or_none(id=row.model_config_id)
            if config is None or config.base_url.rstrip("/") != row.base_url:
                await ModelUsageRecord.filter(id=row.usage_record_id, settlement_status="pending").update(settlement_status="review")
                continue
            path = f"/requests/{row.platform_request_id}" if row.platform_request_id else f"/requests?request_key={quote(str(row.request_key), safe='')}"
            try:
                response = await client.get(row.base_url + path, headers={"Authorization": f"Bearer {config.api_key}"})
                response.raise_for_status()
                receipt = PlatformReceiptOut.model_validate(response.json())
                if row.platform_request_id is None:
                    await StudioCall.filter(id=row.id, platform_request_id=None).update(platform_request_id=receipt.id)
                await settle_platform_call(row.id, receipt)
            except (httpx.HTTPError, ValueError):
                await ModelUsageRecord.filter(id=row.usage_record_id, settlement_status="pending").update(settlement_status="review")
                logger.warning("Platform receipt reconciliation pending call_id=%s", row.id)


async def settle_periodically() -> None:
    while True:
        try:
            await reconcile_platform_calls()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning("Platform receipt cycle failed type=%s", type(error).__name__)
        await asyncio.sleep(5)
