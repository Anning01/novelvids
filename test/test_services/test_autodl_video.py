import json

import httpx
import pytest
from fastapi import HTTPException

from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate
from controllers.config import ai_model_config_controller
from services.model_config_seed import ensure_model_config_seed_data
from services.video import get_generator, get_record_model_type
from services.video.autodl import AutoDLGenerationError, AutoDLVideoGenerator
from services.video.capabilities import capabilities_for
from utils.enums import TaskStatusEnum, VideoModelTypeEnum


@pytest.fixture
def config():
    return AiModelConfig(
        name="autodl-test", task_type=4, task_types=[4], api_key="test-secret",
        model="minimax_h3_zm_u24", base_url="https://autodl.art/api/v1/comfyui",
        api_protocol="autodl", video_model_type="minimax_h3_autodl",
    )


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.asyncio
@pytest.mark.parametrize('resolution,ratio,expected', [
    ('480p', '16:9', '480p横'), ('768p', '9:16', '768p竖'), ('768p', '1:1', '768p(1:1)'),
    ('768p', '16:9', '768p横'), ('480p', '9:16', '480p竖'), ('480p', '1:1', '480p(1:1)'),
])
async def test_submit_contract(monkeypatch, config, resolution, ratio, expected):
    def handler(request):
        assert request.headers['Authorization'] == 'test-secret'
        assert str(request.url) == 'https://autodl.art/api/v1/comfyui/comfyui_workflow/minimax_h3_zm_u24'
        payload = json.loads(request.content)
        assert payload == {
            'prompt': '[图1]说话', 'duration': 5, 'resolution': expected,
            'ref_image_0': 'https://example.com/a.png', 'ref_image_1': 'https://example.com/b.png',
            'ref_audio_0': 'https://example.com/voice.wav',
        }
        return httpx.Response(200, json={'code': 'Success', 'data': {'task_id': 'task-1'}})
    mock_http(monkeypatch, handler)
    generator = get_generator(config)
    assert isinstance(generator, AutoDLVideoGenerator)
    assert get_record_model_type(config) == VideoModelTypeEnum.minimax
    assert await generator.submit('@{主角}说话', duration=5, resolution=resolution, aspect_ratio=ratio,
        subjects=[{'name': '主角', 'images': ['https://example.com/a.png']}],
        reference_images=['https://example.com/a.png', 'https://example.com/b.png'],
        reference_audios=['https://example.com/voice.wav']) == 'task-1'


@pytest.mark.asyncio
async def test_text_only_uses_workflow_blank_image(monkeypatch, config):
    def handler(request):
        payload = json.loads(request.content)
        assert payload['ref_image_0'].endswith('/blank/blank.png')
        assert 'model' not in payload and 'content' not in payload
        return httpx.Response(200, json={'code': 'Success', 'data': {'task_id': 'task'}})
    mock_http(monkeypatch, handler)
    await AutoDLVideoGenerator(config).submit('猫咪', duration=1)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,expected', [
    ('QUEUED', TaskStatusEnum.queued), ('RUNNING', TaskStatusEnum.running),
    ('FAILED', TaskStatusEnum.failed), ('error', TaskStatusEnum.failed),
    ('CANCELLED', TaskStatusEnum.cancelled), ('SUCCESS', TaskStatusEnum.completed),
    ('completed', TaskStatusEnum.completed),
])
async def test_query_contract(monkeypatch, config, status, expected):
    def handler(request):
        assert request.method == 'GET'
        assert str(request.url).endswith('/comfyui_workflow/result/task-1')
        return httpx.Response(200, json={'code': 'Success', 'data': {
            'status': status, 'duration': 300,
            'results': [{'type': 'image', 'url': 'https://example.com/preview.png'},
                        {'type': 'video', 'url': 'https://example.com/video.mp4'}],
        }})
    mock_http(monkeypatch, handler)
    result = await AutoDLVideoGenerator(config).query('task-1')
    assert result['status'] == expected
    assert 'duration' not in result['metadata']  # 推理耗时不能用于计费
    if expected == TaskStatusEnum.completed:
        assert result['url'] == 'https://example.com/video.mp4'
        assert result['progress'] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, [], {'code': 'Error', 'msg': 'test-secret'},
    {'code': 'Success', 'data': None}, {'code': 'Success', 'data': {}},
    {'code': 'Success', 'data': {'status': 'UNKNOWN'}},
    {'code': 'Success', 'data': {'status': 'SUCCESS', 'results': []}},
    {'code': 'Success', 'data': {'status': 'SUCCESS', 'results': [{'type': 'video', 'url': 'file:///tmp/a.mp4'}]}},
])
async def test_malformed_response_is_safe(monkeypatch, config, body):
    mock_http(monkeypatch, lambda req: httpx.Response(200, json=body) if body is not None else httpx.Response(200, text='bad json test-secret'))
    with pytest.raises(AutoDLGenerationError) as exc:
        await AutoDLVideoGenerator(config).query('task')
    assert 'test-secret' not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 429, 500])
async def test_http_error_does_not_expose_response(monkeypatch, config, status):
    mock_http(monkeypatch, lambda req: httpx.Response(status, text='test-secret'))
    with pytest.raises(AutoDLGenerationError, match=str(status)) as exc:
        await AutoDLVideoGenerator(config).submit('cat')
    assert 'test-secret' not in str(exc.value)


@pytest.mark.asyncio
async def test_network_error(monkeypatch, config):
    def handler(request):
        raise httpx.ConnectError('test-secret', request=request)
    mock_http(monkeypatch, handler)
    with pytest.raises(AutoDLGenerationError, match='网络请求失败'):
        await AutoDLVideoGenerator(config).query('task')


@pytest.mark.asyncio
@pytest.mark.parametrize('kwargs', [
    {'reference_videos': ['https://example.com/v.mp4']},
    {'first_frame_url': 'https://example.com/a.png'},
    {'reference_images': ['data:image/png;base64,abc']},
    {'reference_audios': ['asset://voice']},
    {'reference_images': [f'https://example.com/{i}.png' for i in range(10)]},
    {'reference_audios': [f'https://example.com/{i}.wav' for i in range(4)]},
    {'generation_mode': 'keyframes'}, {'resolution': '2K'}, {'aspect_ratio': '4:3'},
    {'duration': 16}, {'duration': -1},
])
async def test_unsupported_inputs_rejected_before_request(config, kwargs):
    with pytest.raises((AutoDLGenerationError, HTTPException)):
        await AutoDLVideoGenerator(config).submit('cat', **kwargs)


@pytest.mark.asyncio
async def test_config_initialization_restart_and_existing_config_preserved():
    await ensure_model_config_seed_data()
    config = await AiModelConfig.get(name='minimax-h3-autodl')
    assert config.is_active is False
    assert config.api_protocol == 'autodl'
    assert config.pricing['billing_unit'] == 'second'
    config.model = 'custom-workflow'
    await config.save()
    assert await ensure_model_config_seed_data() == 0
    await config.refresh_from_db()
    assert config.model == 'custom-workflow'
    assert await AiModelConfig.filter(name='minimax-h3-autodl').count() == 1
    assert (await AiModelConfig.get(name='minimax-h3')).api_protocol == 'minimax'


@pytest.mark.asyncio
async def test_config_create_and_capability_contract(config):
    created = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=4, task_types=[4], name=config.name, api_key=config.api_key,
        model=config.model, base_url=config.base_url, api_protocol='autodl',
        video_model_type='minimax_h3_autodl',
        pricing={'type': 'video', 'currency': 'CNY', 'billing_unit': 'second', 'prices': {'480p': 0.04, '768p': 0.05}},
    ))
    assert isinstance(get_generator(created), AutoDLVideoGenerator)
    caps = capabilities_for(created.video_model_type)
    assert caps.max_reference_videos == 0
    assert caps.generation_modes == ('reference',)
    assert caps.duration_min == 1
