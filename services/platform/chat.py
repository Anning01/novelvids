"""OpenAI-compatible text transport. Content stays in memory; durable receipts contain costs only."""
import asyncio
import json
import logging

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from openai import APIError, APIStatusError, AsyncOpenAI
from auth.models import PlatformCallReceipt
from services.platform.calls import CALL_TIMEOUT, admit, finish, recover_measured
from services.platform.http_contract import UpstreamResponseError, error_body, redact_secret

logger = logging.getLogger(__name__)
_streams = set()


def provider_client(config):
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key, max_retries=0, timeout=CALL_TIMEOUT)


def public_completion(message, public_model):
    return {**message.model_dump(mode="json", exclude_unset=True), "model":public_model}


async def mark_failure(receipt, exc):
    rejected = isinstance(exc, APIStatusError) and 400 <= exc.status_code < 500 and exc.status_code != 408
    await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected" if rejected else "review")


RESULT_UNCONFIRMED = "平台未能确认完整模型结果，请凭请求编号查询状态"


class ChatStream(StreamingResponse):
    def __init__(self, client, stream, receipt, model, include_usage, deadline, secret=""):
        self.queue = asyncio.Queue(maxsize=32)
        self.detached = False
        super().__init__(self.events(), media_type="text/event-stream",
            headers={"X-Request-Id":str(receipt.public_id),"Cache-Control":"no-store","X-Accel-Buffering":"no"})
        task = asyncio.create_task(self.drain(client, stream, receipt, model, include_usage, deadline, secret))
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

    async def drain(self, client, stream, receipt, model, include_usage, deadline, secret):
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
            await mark_failure(receipt, exc)
            payload = error_body(502, RESULT_UNCONFIRMED)
            if isinstance(exc, APIError) and isinstance(exc.body, dict):
                payload = exc.body if "error" in exc.body else {"error": exc.body}
            logger.warning("Developer chat stream failed request_id=%s type=%s", receipt.public_id, type(exc).__name__)
            content = redact_secret(json.dumps(payload, ensure_ascii=False).encode(), secret)
            await self.put(b"data: " + content + b"\n\n")
        finally:
            try:
                await client.close()
            finally:
                await self.put(None)


async def complete(ctx, body, key):
    params = body.model_dump(mode="json", exclude_unset=True)
    config, receipt = await admit(ctx, body.model, params, key)
    headers = {"X-Request-Id":str(receipt.public_id), "Cache-Control":"no-store"}
    client = None
    deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT
    try:
        client = provider_client(config)
        params["model"] = config.model
        params.setdefault("stream", False)
        if config.max_tokens and not (body.max_tokens or body.max_completion_tokens):
            params["max_tokens"] = config.max_tokens
        if body.stream:
            params["stream_options"] = {**(body.stream_options or {}), "include_usage":True}
        extra = {name: params.pop(name) for name in (body.model_extra or {}) if name in params}
        if body.thinking is not None:
            extra["thinking"] = params.pop("thinking")
        if extra:
            params["extra_body"] = extra
        async with asyncio.timeout_at(deadline):
            raw_result = await client.chat.completions.with_raw_response.create(**params)
            if not body.stream and raw_result.http_response.json().get("error"):
                await PlatformCallReceipt.filter(id=receipt.id, state="submitted").update(state="rejected")
                raise UpstreamResponseError(raw_result.http_response, str(receipt.public_id), config.api_key)
            result = raw_result.parse()
        if body.stream:
            response = ChatStream(client, result, receipt, body.model,
                                  bool((body.stream_options or {}).get("include_usage")), deadline, config.api_key)
            client = None  # Stream owns its transport until usage is collected.
            return response
        await finish(receipt, result.usage, result.id)
        return JSONResponse(public_completion(result, body.model), headers=headers)
    except asyncio.CancelledError as exc:
        await mark_failure(receipt, exc)
        raise
    except Exception as exc:
        await mark_failure(receipt, exc)
        if isinstance(exc, UpstreamResponseError):
            raise
        if isinstance(exc, APIStatusError):
            raise UpstreamResponseError(exc.response, str(receipt.public_id), config.api_key) from None
        logger.warning("Developer chat request failed request_id=%s type=%s", receipt.public_id, type(exc).__name__)
        raise HTTPException(502, RESULT_UNCONFIRMED, headers=headers) from None
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
