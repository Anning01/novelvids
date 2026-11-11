"""OpenAI-compatible text transport. Content stays in memory; durable receipts contain costs only."""
import asyncio
import json
import logging

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from openai import APIStatusError, AsyncOpenAI
from auth.models import PlatformCallReceipt
from services.platform.calls import CALL_TIMEOUT, admit, finish, recover_measured

logger = logging.getLogger(__name__)
_streams = set()


def provider_client(config):
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key, max_retries=0, timeout=CALL_TIMEOUT)


def public_completion(message, public_model):
    payload = message.model_dump(mode="json", exclude_none=True)
    allowed = ("id", "object", "created", "choices", "usage", "system_fingerprint")
    return {**{k:payload[k] for k in allowed if k in payload}, "model":public_model}


async def mark_failure(receipt, exc):
    rejected = isinstance(exc, APIStatusError) and 400 <= exc.status_code < 500 and exc.status_code != 408
    await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected" if rejected else "review")
    if isinstance(exc, APIStatusError) and exc.status_code == 429:
        return 429, "上游模型繁忙，请稍后重试"
    if rejected and exc.status_code in (400, 413, 422):
        return 422, "上游模型不接受此次请求参数"
    return 502, "平台未能确认完整模型结果，请凭请求编号查询状态"


class ChatStream(StreamingResponse):
    def __init__(self, client, stream, receipt, model, include_usage, deadline):
        self.queue = asyncio.Queue(maxsize=32)
        self.detached = False
        super().__init__(self.events(), media_type="text/event-stream",
            headers={"X-Request-Id":str(receipt.public_id),"Cache-Control":"no-store","X-Accel-Buffering":"no"})
        task = asyncio.create_task(self.drain(client, stream, receipt, model, include_usage, deadline))
        _streams.add(task)
        task.add_done_callback(_streams.discard)

    async def put(self, item):
        if not self.detached:
            await self.queue.put(item)

    async def events(self):
        while (event := await self.queue.get()) is not None:
            yield event

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.detached = True
            # Wake the single producer if a disconnected client left its queue full.
            while not self.queue.empty():
                self.queue.get_nowait()

    async def drain(self, client, stream, receipt, model, include_usage, deadline):
        usage = None
        provider_id = None
        try:
            async with asyncio.timeout_at(deadline):
                async for chunk in stream:
                    if provider_id is None and chunk.id:
                        provider_id = chunk.id
                        await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(provider_id=provider_id)
                    if chunk.usage is not None:
                        usage = chunk.usage
                    data = public_completion(chunk, model)
                    if not include_usage:
                        data.pop("usage", None)
                        if not chunk.choices:
                            continue
                    await self.put("data: " + json.dumps(data, ensure_ascii=False) + "\n\n")
            await finish(receipt, usage, provider_id)
            await self.put("data: [DONE]\n\n")
        except asyncio.CancelledError as exc:
            await mark_failure(receipt, exc)
            raise
        except Exception as exc:
            code, message = await mark_failure(receipt, exc)
            await self.put("data: " + json.dumps({"error":{"code":code, "message":message},
                "request_id":str(receipt.public_id)}, ensure_ascii=False) + "\n\n")
        finally:
            try:
                await client.close()
            finally:
                await self.put(None)


async def complete(ctx, body, key):
    params = body.model_dump(mode="json", exclude_none=True)
    config, receipt = await admit(ctx, int(body.model[3:]), params, key)
    headers = {"X-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    client = None
    deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT
    try:
        client = provider_client(config)
        params["model"] = config.model
        if config.max_tokens and not (body.max_tokens or body.max_completion_tokens):
            params["max_tokens"] = config.max_tokens
        if body.stream:
            params["stream_options"] = {"include_usage":True}
        if body.thinking is not None:
            params["extra_body"] = {"thinking":params.pop("thinking")}
        async with asyncio.timeout_at(deadline):
            result = await client.chat.completions.create(**params)
        if body.stream:
            response = ChatStream(client, result, receipt, body.model,
                                  bool((body.stream_options or {}).get("include_usage")), deadline)
            client = None  # Stream owns its transport until usage is collected.
            return response
        await finish(receipt, result.usage, result.id)
        return JSONResponse(public_completion(result, body.model), headers=headers)
    except asyncio.CancelledError as exc:
        await mark_failure(receipt, exc)
        raise
    except Exception as exc:
        code, message = await mark_failure(receipt, exc)
        raise HTTPException(code, message, headers=headers) from None
    finally:
        if client is not None:
            await client.close()


async def settle_periodically():
    while True:
        await asyncio.sleep(60)
        try:
            await recover_measured()
        except Exception:
            logger.error("Platform settlement retry deferred")


async def stop_streams():
    if _streams:
        _, pending = await asyncio.wait(list(_streams), timeout=15)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
