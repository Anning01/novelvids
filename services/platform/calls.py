"""Admit a developer request once and atomically settle a provider-reported usage snapshot."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from math import isfinite
from uuid import uuid4

from fastapi import HTTPException
from tortoise.expressions import F
from tortoise.transactions import in_transaction

from auth.models import PlatformCallReceipt
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.balance import accumulate_member_cost, consume, ensure_solvent
from services.billing.pricing import compute_text_cost
from utils.enums import AiTaskTypeEnum

CALL_TIMEOUT = 600


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def text_pricing(config):
    rates = config.pricing or {}
    if rates.get("type") != "text" or not all(
        type(rates.get(k)) in {float, int} and isfinite(rates[k]) and rates[k] >= 0
        for k in ("input_price_per_1m", "output_price_per_1m")
    ):
        raise HTTPException(422, "所选模型尚未配置文本调用价格")
    return rates


async def admit(ctx, model_id, body, key):
    identifier = uuid4()
    dedup = digest([ctx.team_id, ctx.user.id, key or str(identifier)])
    signature = digest(body)
    async with in_transaction() as db:
        selected = AiModelConfig.filter(id=model_id, scope="official", team_id__isnull=True, is_active=True).using_db(db)
        # Serialize admission across workers before checking concurrency or a repeated key.
        if not await selected.update(concurrency=F("concurrency")):
            raise HTTPException(404, "平台模型不存在或已停用")
        config = await selected.get()
        previous = await PlatformCallReceipt.get_or_none(dedup_key=dedup).using_db(db)
        if previous:
            detail = "请求标识已用于不同的请求" if previous.payload_hash != signature else "该请求已受理，请查询原请求状态"
            raise HTTPException(409, detail, headers={"X-Request-Id":str(previous.public_id)})
        if not set(config.task_types or [config.task_type]).intersection({1,3,5,6,7,10,11}):
            raise HTTPException(422, "该模型不支持对话请求")
        if body.get("tools") and not config.supports_tool_calls:
            raise HTTPException(422, "该模型配置未启用工具调用")
        if body.get("response_format", {}).get("type") in {"json_object", "json_schema"} and not config.supports_json_output:
            raise HTTPException(422, "该模型配置未启用结构化输出")
        requested = body.get("max_tokens") or body.get("max_completion_tokens")
        if requested and config.max_tokens and requested > config.max_tokens:
            raise HTTPException(422, "请求的输出 token 超出模型配置上限")
        rates = text_pricing(config)
        await ensure_solvent(ctx.team_id, ctx.user.id)
        count = await PlatformCallReceipt.filter(model_config_id=model_id, state="submitted",
            created_at__gte=datetime.now(timezone.utc)-timedelta(seconds=CALL_TIMEOUT+15)).using_db(db).count()
        if count >= config.concurrency:
            raise HTTPException(429, "模型并发已满，请稍后重试", headers={"Retry-After":"2"})
        receipt = await PlatformCallReceipt.create(using_db=db, public_id=identifier, dedup_key=dedup,
            payload_hash=signature, team_id=ctx.team_id, user_id=ctx.user.id, model_config_id=config.id,
            model_name=config.name, model=config.model, pricing=rates)
    return config, receipt


async def settle(receipt_id):
    async with in_transaction() as db:
        # Claiming the state is also the SQLite write lock. Rollback preserves a retryable measurement.
        changed = await PlatformCallReceipt.filter(id=receipt_id, state="measured").using_db(db).update(state="settling")
        if not changed:
            return
        r = await PlatformCallReceipt.get(id=receipt_id).using_db(db)
        cost = compute_text_cost(r.usage, r.pricing)
        record = await ModelUsageRecord.create(using_db=db, novel_id=0, task_type=AiTaskTypeEnum.creation_agent,
            billing_type="text", model_config_id=r.model_config_id, model_name=r.model_name, model=r.model,
            pricing_snapshot=r.pricing, usage={**r.usage, "platform_request_id":str(r.public_id)},
            cost=cost, cost_source="balance", team_id=r.team_id, user_id=r.user_id)
        await consume(r.team_id, cost, usage_record_id=record.id, strict=True)
        await accumulate_member_cost(r.team_id, r.user_id, cost, strict=True)
        await PlatformCallReceipt.filter(id=r.id).using_db(db).update(state="completed", usage_record_id=record.id)


async def finish(receipt, usage, provider_id):
    if usage is None or any(type(v) is not int or v < 0 for v in (usage.prompt_tokens, usage.completion_tokens)):
        await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="review", provider_id=provider_id)
        raise ValueError("Missing provider token counts")
    from services.llm.usage import completion_cache_usage
    tokens = {"input_tokens":usage.prompt_tokens, "output_tokens":usage.completion_tokens, **completion_cache_usage(usage)}
    await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(
        state="measured", usage=tokens, provider_id=provider_id)
    await settle(receipt.id)


async def recover_measured():
    for receipt_id in await PlatformCallReceipt.filter(state="measured").values_list("id", flat=True):
        await settle(receipt_id)
    await PlatformCallReceipt.filter(state="submitted", created_at__lt=datetime.now(timezone.utc)-timedelta(seconds=CALL_TIMEOUT+15)).update(state="review")
