"""Cat API admission and settlement for non-streaming VoiceDesign chat calls."""

import asyncio
import logging

import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from auth.models import PlatformCallReceipt
from services.billing.pricing import validate_voice_design_pricing
from services.platform.calls import CALL_TIMEOUT, admit, record_measurement
from services.platform.chat import RESULT_UNCONFIRMED
from services.platform.request_data import validated_body
from schemas.voice_design import VoiceDesignRequest
from services.voice_design_protocol import VOICE_PROTOCOLS, synthesize_voice
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message as msg

logger = logging.getLogger(__name__)


def voice_options(config, _body):
    if (AiTaskTypeEnum.voice_design not in (config.task_types or [config.task_type])
            or config.api_protocol not in VOICE_PROTOCOLS - {"novelvids"} or not config.api_key):
        raise HTTPException(422, msg("该模型不支持音色设计请求"))
    try:
        return validate_voice_design_pricing(config.pricing)
    except ValueError:
        raise HTTPException(422, msg("请填写有效的音色设计每秒价格")) from None


async def complete_voice_design(ctx, params, key):
    body = validated_body(VoiceDesignRequest, params)
    config, receipt = await admit(ctx, body.model, body.model_dump(mode="json"), key,
                                  validate=voice_options, kind="voice_design")
    request_id = str(receipt.public_id)
    headers = {"X-Request-Id": request_id, "X-Cat-Request-Id": request_id, "Cache-Control": "no-store"}
    try:
        async with asyncio.timeout(CALL_TIMEOUT), httpx.AsyncClient(
            timeout=CALL_TIMEOUT, follow_redirects=False, trust_env=False,
        ) as client:
            result = await synthesize_voice(client, config, body)
        await record_measurement(receipt, {"seconds": result.seconds}, result.response.get("id"))
    except asyncio.CancelledError:
        await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="review")
        raise
    except Exception as error:
        rejected = isinstance(error, httpx.HTTPStatusError) and 400 <= error.response.status_code < 500 and error.response.status_code != 408
        await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected" if rejected else "review")
        logger.warning("Voice design API call failed request_id=%s type=%s", receipt.public_id, type(error).__name__)
        raise HTTPException(502, msg(RESULT_UNCONFIRMED), headers=headers) from None
    upstream = result.response
    choice = upstream["choices"][0]
    return JSONResponse({
        "id": upstream.get("id") or request_id,
        "object": "chat.completion",
        "created": upstream.get("created", int(receipt.created_at.timestamp())),
        "model": body.model,
        "choices": [{
            "index": 0,
            "finish_reason": choice.get("finish_reason") or "stop",
            "message": {"role": "assistant", "content": None, "audio": choice["message"]["audio"]},
        }],
    }, headers=headers)
