from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.remake.capacity_transport import PlatformCapacityTransport


@pytest.mark.asyncio
async def test_capacity_wait_reuses_request_until_admitted():
    request = httpx.Request("POST", "https://example.test/chat/completions", content=b'{}',
                            headers={"Idempotency-Key": "same-request"})
    busy = lambda: httpx.Response(429, json={"error": {"code": "rate_limit_exceeded",
        "message": "模型并发已满，请稍后重试"}}, headers={"Retry-After": "2"}, request=request)
    accepted = httpx.Response(200, content=b'ok', request=request)
    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request",
                      AsyncMock(side_effect=[busy(), busy(), accepted])) as send,          patch("services.remake.capacity_transport.asyncio.sleep", AsyncMock()) as sleep:
        async with PlatformCapacityTransport() as transport:
            assert await transport.handle_async_request(request) is accepted
        assert send.await_count == 3
        assert all(call.args[0] is request for call in send.await_args_list)
        assert sleep.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,message", [
    ({"X-Cat-Request-Id": "accepted"}, "模型并发已满，请稍后重试"),
    ({}, "上游请求限流"),
])
async def test_does_not_replay_accepted_or_unknown_limits(headers, message):
    response = httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": message}}, headers=headers)
    with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(return_value=response)) as send:
        async with PlatformCapacityTransport() as transport:
            assert await transport.handle_async_request(httpx.Request("POST", "https://example.test")) is response
        assert send.await_count == 1


@pytest.mark.asyncio
async def test_wait_can_be_cancelled_and_exports_capacity_details():
    import asyncio
    from types import SimpleNamespace
    from services.billing.platform import active_model_call
    call = {}
    token = active_model_call.set((SimpleNamespace(), call))
    response = httpx.Response(429, json={"error": {"code": "rate_limit_exceeded",
        "message": "模型并发已满，请稍后重试"}}, headers={"Retry-After": "3"})
    try:
        with patch.object(httpx.AsyncHTTPTransport, "handle_async_request", AsyncMock(return_value=response)),              patch("services.remake.capacity_transport.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            async with PlatformCapacityTransport() as transport:
                with pytest.raises(asyncio.CancelledError):
                    await transport.handle_async_request(httpx.Request("POST", "https://example.test"))
        assert call == {"rate_limit_reason": "model_concurrency", "retry_after_seconds": 3, "admission_retry_count": 1}
        assert response.is_closed
    finally:
        active_model_call.reset(token)
