"""A revoked upstream key must pause polling, not lose or resubmit accepted videos."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from controllers.video import video_controller
from models.ai_task import AiTask
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from models.scene import Scene
from models.video import Video


@pytest.mark.asyncio
@pytest.mark.parametrize('http_status', [401, 403])
async def test_revoked_provider_key_pauses_query_and_recovers_same_video_after_reconnect(http_status, client):
    novel = await Novel.create(name='Recover accepted video')
    chapter = await Chapter.create(novel=novel, number=1, name='one', content='test')
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='test', duration=8)
    config = await AiModelConfig.create(task_type=4, name='video', model='nv-test', api_key='revoked-test-key',
        base_url='https://example.test/v1', api_protocol='novelvids', video_model_type='minimax_h3', is_active=True)
    task = await AiTask.create(task_type=4, status=2, stage='waiting_media')
    video = await Video.create(scene=scene, model_type=1, status=2, external_task_id='accepted-original', metadata={
        'model_config_id': config.id, 'novel_id': novel.id, 'agent_run_id': str(task.id), 'duration': 8})
    sent = []
    async def send(_transport, request):
        sent.append(request)
        if request.headers['Authorization'] == 'Bearer revoked-test-key':
            return httpx.Response(http_status, json={'error': {'message': 'secret provider error', 'code': 'invalid_api_key'}})
        return httpx.Response(200, json={'id': 'accepted-original', 'status': 'completed',
            'metadata': {'url': 'https://example.test/result.mp4', 'duration': 8}})
    with patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', send), \
            patch('controllers.video._download_video', AsyncMock(return_value=('/media/result.mp4', {}))), \
            patch('services.creation_agent.video_settlement.settle_video', AsyncMock()):
        for _ in range(2):
            with pytest.raises(HTTPException) as error:
                await video_controller.query_status(video.id)
            assert error.value.status_code == 409
            assert '重新连接' in str(error.value.detail)
            assert 'secret' not in str(error.value.detail)
        response = await client.get(f'/api/video/query/{video.id}')
        assert response.status_code != 500
        assert response.json()['code'] == 409
        assert len(sent) == 1
        await video.refresh_from_db()
        assert video.status == 2 and video.external_task_id == 'accepted-original'
        config.api_key = 'replacement-test-key'
        await config.save(update_fields=['api_key', 'updated_at'])
        result = await video_controller.query_status(video.id)
        assert result.status == 3 and result.url == '/media/result.mp4'
        assert not result.metadata.get('query_blocked')
        assert len(sent) == 2 and all(request.method == 'GET' for request in sent)
        assert all(request.url.path.endswith('/accepted-original') for request in sent)
        assert await Video.all().count() == 1
