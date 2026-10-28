from decimal import Decimal

import httpx
import pytest

from services.video_enhancement.contract import EnhancementOptions, MediaProbe, enhancement_cost, validate_source
from services.video_enhancement.provider import MediaKitClient, MediaKitError


def options():
    return EnhancementOptions()


def probe(**values):
    return MediaProbe(duration=5, width=864, height=496, fps=24, **values)


@pytest.mark.parametrize('fps,expected,minute', [(29.97, '0.416667', 5), (30, '0.416667', 5), (30.01, '0.833333', 10), (60, '0.833333', 10), (60.01, '1.666667', 20)])
def test_enhancement_prices_actual_milliseconds_and_fps(fps, expected, minute):
    pricing = {'type': 'media_processing', 'billing_unit': 'minute', 'tiers': [
        {'short_side_max': 1080, 'fps_max': 30, 'price': 5},
        {'short_side_max': 1080, 'fps_max': 60, 'price': 10},
        {'short_side_max': 1080, 'fps_max': 120, 'price': 20},
    ]}
    assert enhancement_cost(5, 1080, fps, pricing) == Decimal(expected)
    assert enhancement_cost(60, 1080, fps, pricing) == Decimal(minute)
    assert enhancement_cost('5.001', 1080, 30, pricing) == Decimal('0.416750')
    with pytest.raises(ValueError):
        enhancement_cost(None, 1080, fps, pricing)


def test_source_limits_are_explicit_and_portrait_is_supported():
    validate_source(probe(), options())
    validate_source(MediaProbe(duration=5, width=480, height=854, fps=29.97), options())
    with pytest.raises(ValueError):
        validate_source(MediaProbe(duration=5, width=320, height=180, fps=24), options())
    with pytest.raises(ValueError):
        validate_source(probe(color_transfer='smpte2084'), options())
    with pytest.raises(ValueError):
        validate_source(probe(), options().model_copy(update={'max_duration_seconds': Decimal('4')}))


@pytest.mark.asyncio
async def test_media_kit_submission_and_query_are_not_confused_with_completion():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'success': True, **(
            {'task_id': 'accepted-123'} if request.method == 'POST' else
            {'task_id': 'accepted-123', 'status': 'running'}
        )})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = MediaKitClient('https://mediakit.example', 'secret-never-log', http=http)
        assert await client.submit('https://media.example/source.mp4', 'stable-operation') == 'accepted-123'
        assert (await client.query('accepted-123')).status == 'running'
    import json
    sent = json.loads(requests[0].content)
    assert sent == {'video_url': 'https://media.example/source.mp4', 'resolution': '1080p', 'client_token': 'stable-operation'}
    assert requests[0].url.path == '/api/v1/tools/enhance-video-generative'
    assert requests[1].url.path == '/api/v1/tasks/accepted-123'


@pytest.mark.asyncio
async def test_provider_error_redacts_secrets_and_signed_urls():
    def respond(_request):
        return httpx.Response(403, json={'error': {'code': 'Denied', 'message': 'secret-never-log https://x/?token=private'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(MediaKitError) as caught:
            await MediaKitClient('https://mediakit.example', 'secret-never-log', http=http).query('id')
    assert 'secret-never-log' not in str(caught.value)
    assert 'private' not in str(caught.value)


@pytest.mark.asyncio
async def test_local_upload_streams_raw_binary_without_forwarding_service_key(tmp_path):
    path=tmp_path/'source.mp4';path.write_bytes(b'video-binary')
    requests=[]
    async def respond(request):
        requests.append(request)
        if request.method=='POST':
            return httpx.Response(200,json={'success':True,'result':{'file_id':'mediakit://temporary-file',
                'method':'PUT','upload_url':'https://upload.example/path?signature=private',
                'upload_headers':[{'key':'Content-Type','value':'video/mp4'}]}})
        assert await request.aread()==b'video-binary'
        assert 'authorization' not in request.headers
        assert request.headers['content-type']=='video/mp4'
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client=MediaKitClient('https://mediakit.example','secret',http=http)
        assert await client.upload(path,max_bytes=1024)=='mediakit://temporary-file'
    assert len(requests)==2


def test_snapshot_endpoint_changes_never_send_current_credentials_to_old_service():
    from types import SimpleNamespace
    snapshot = {'base_url':'https://original.example', 'api_protocol':'volcengine_mediakit', 'model':'enhance-video-generative'}
    config = SimpleNamespace(**snapshot, api_key='rotated-current-key')
    client = MediaKitClient.for_snapshot(snapshot,config,http=None)
    assert client.api_key == config.api_key
    config.base_url = 'https://changed.example'
    with pytest.raises(MediaKitError):
        MediaKitClient.for_snapshot(snapshot,config,http=None)
