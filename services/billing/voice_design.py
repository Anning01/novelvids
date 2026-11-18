"""Record the two measured model calls independently of the subsequent asset write."""

from time import monotonic

import httpx
from fastapi import HTTPException
from tortoise.transactions import in_transaction

from services.balance import ensure_solvent
from services.billing.platform import begin_platform_call, capture_platform_response, finish_model_call, is_platform_model
from services.billing.pricing import compute_voice_design_cost
from services.billing.recorder import billing_recorder, _consume_team_balance
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.messages import localized_message as msg


async def run_voice_model(config, *, project, user_id, kind, execute):
    owner = {"novel_id": project.id, "team_id": project.team_id, "user_id": user_id}
    platform = is_platform_model(config)
    call = {}
    headers = {}
    if platform:
        row = await begin_platform_call(config, billing_type=kind, attribution=owner,
                                        task_type=AiTaskTypeEnum.voice_design.value)
        call["studio_call_id"] = row.id
        headers["Idempotency-Key"] = str(row.request_key)
    elif config.scope != "team":
        await ensure_solvent(project.team_id, user_id)

    async def capture(response):
        if platform:
            await capture_platform_response(row, response)

    start = monotonic()
    usage = {}
    completed = False
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=False, trust_env=False,
                                     headers=headers, event_hooks={"response": [capture]}) as client:
            result, usage = await execute(client)
        completed = True
        return result
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 402:
            raise HTTPException(402, msg("模型账户可用额度不足")) from None
        raise HTTPException(502, msg("音色设计模型调用失败，请检查模型配置后重试")) from None
    except httpx.RequestError:
        raise HTTPException(502, msg("音色设计模型调用失败，请检查模型配置后重试")) from None
    finally:
        duration = monotonic() - start
        if platform:
            await finish_model_call(call, completed=completed, usage=usage, duration=duration)
        elif usage:
            await record_voice_usage(config, owner, kind, usage, duration)


async def record_voice_usage(config, owner, kind, usage, duration):
    status = TaskStatusEnum.completed.value
    task_type = AiTaskTypeEnum.voice_design.value
    async with in_transaction():
        if kind == "text":
            record = await billing_recorder.record_text(
                task_type=task_type, config_snapshot=config, token_usage=usage,
                duration_seconds=duration, status=status, **owner,
            )
        else:
            record = await billing_recorder._create(
                task_type=task_type, billing_type=kind, config=config, fallback_model=None,
                usage=usage, cost=compute_voice_design_cost(usage["seconds"], config.pricing),
                duration_seconds=duration, status=status, **owner,
            )
        if record is None:
            raise HTTPException(503, msg("音色设计用量暂未保存"))
        await _consume_team_balance(record, owner["team_id"], owner["user_id"], strict=True)
