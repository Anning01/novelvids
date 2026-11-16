"""Only a platform admission rejection may be retried before video submission."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from services.video.base import VideoProviderError
from services.video.unified import UnifiedVideoGenerator


def generator():
    return UnifiedVideoGenerator(SimpleNamespace(api_protocol='novelvids',
        base_url='https://example.test', api_key='test'))


def busy(headers=None, message='模型并发已满，请稍后重试'):
    return httpx.Response(429, json={'error': {'code': 'rate_limit_exceeded', 'message': message}},
        headers=headers or {'Retry-After': '2'})


@pytest.mark.asyncio
async def test_video_waits_for_admission_and_reuses_original_request():
    accepted = httpx.Response(200, json={'id': 'accepted-video', 'status': 'queued'})
    with patch.object(httpx.AsyncHTTPTransport, 'handle_async_request',
            AsyncMock(side_effect=[busy(), busy(), accepted])) as send, \
            patch('services.remake.capacity_transport.asyncio.sleep', AsyncMock()) as sleep:
        result = await generator()._request('POST', payload={'request_id': 'same-id', 'prompt': 'test'})
    assert result['id'] == 'accepted-video'
    assert send.await_count == 3
    assert all(call.args[0] is send.await_args_list[0].args[0] for call in send.await_args_list)
    assert sleep.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('headers,message', [
    ({'X-Cat-Request-Id': 'accepted'}, '模型并发已满，请稍后重试'),
    ({'X-Novelvids-Request-Id': 'accepted'}, '模型并发已满，请稍后重试'),
    ({'X-Request-Id': 'upstream'}, '模型并发已满，请稍后重试'),
    ({}, '额度不足'),
])
async def test_video_does_not_replay_accepted_or_other_429(headers, message):
    with patch.object(httpx.AsyncHTTPTransport, 'handle_async_request',
            AsyncMock(return_value=busy(headers, message))) as send:
        with pytest.raises(VideoProviderError):
            await generator()._request('POST', payload={'request_id': 'same-id'})
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_video_admission_wait_can_be_cancelled_without_another_submission():
    import asyncio
    with patch.object(httpx.AsyncHTTPTransport, 'handle_async_request',
            AsyncMock(return_value=busy())) as send, \
            patch('services.remake.capacity_transport.asyncio.sleep', AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await generator()._request('POST', payload={'request_id': 'same-id'})
    assert send.await_count == 1


@pytest.mark.asyncio
async def test_nonplatform_429_is_not_retried():
    direct = generator()
    direct.config.api_protocol = 'unified_video'
    with patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', AsyncMock(return_value=busy())) as send:
        with pytest.raises(VideoProviderError):
            await direct._request('POST', payload={'request_id': 'same-id'})
    assert send.await_count == 1
