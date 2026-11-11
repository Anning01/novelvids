import base64
import json
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import AsyncMock

import cv2
import httpx
import numpy as np
import pytest
from fastapi import HTTPException

from prompts.image_animation import render_gif_prompt
from services.image_generation.capabilities import GIF_IMAGE_MODELS, capabilities_for, validate_selection
from services.reference.generator import generate_for_sora_consistency
from services.reference.handler import _content_type_for, _persist_generated_image
from utils.enums import ImageModelTypeEnum


def gif_bytes():
    animation = cv2.Animation()
    animation.frames = [np.full((16, 16, 3), color, dtype=np.uint8) for color in (32, 192)]
    animation.durations = [200, 200]
    success, encoded = cv2.imencodeanimation('.gif', animation)
    assert success
    return encoded.tobytes()


@pytest.mark.parametrize('model_type', list(ImageModelTypeEnum))
def test_only_configured_gpt_image_26_types_accept_gif(model_type):
    options = dict(clarity=None, aspect_ratio='1:1', output_format='gif', generation_count=1, frame_count=4, frame_duration_ms=100)
    if model_type in GIF_IMAGE_MODELS:
        selected = validate_selection(model_type, **options)
        assert selected.output_format == 'gif'
        assert selected.frame_count == 4
        assert selected.frame_duration_ms == 100
        assert selected.provider_quality == '1k'
        assert capabilities_for(model_type).public_dict()['frame_counts'] == list(range(2, 17))
    else:
        with pytest.raises(HTTPException, match='格式'):
            validate_selection(model_type, **options)
    with pytest.raises(HTTPException, match='格式'):
        validate_selection(model_type, **{**options, 'output_format': 'svg'})


@pytest.mark.parametrize('field,value', [('frame_count',1),('frame_count',17),('frame_count','9'),('frame_count',True),
    ('frame_duration_ms',19),('frame_duration_ms',655351),('frame_duration_ms','200'),('frame_duration_ms',True)])
def test_gif_frame_options_are_validated_before_submission(field, value):
    with pytest.raises(HTTPException, match='帧'):
        validate_selection('gpt_image_2_6', clarity=None, aspect_ratio='1:1',
            output_format='gif', generation_count=1, **{field:value})


def test_gif_defaults_and_interval_rounding_follow_wire_contract():
    selected=validate_selection('gpt_image_2_6',clarity=None,aspect_ratio='1:1',output_format='gif',generation_count=1)
    assert (selected.frame_count,selected.frame_duration_ms)==(9,200)
    rounded=validate_selection('gpt_image_2_6',clarity=None,aspect_ratio='1:1',output_format='gif',generation_count=1,frame_duration_ms=25)
    assert rounded.frame_duration_ms==30


async def test_full_gif_wire_request_uses_explicit_gif_and_supported_1k_parameters(monkeypatch):
    selection = validate_selection('gpt_image_2_6', clarity='1K', aspect_ratio='1:1',
        output_format='gif', generation_count=1, frame_count=8, frame_duration_ms=250)
    async def handler(request):
        assert str(request.url) == 'https://custom.example/proxy/v1/images/generations'
        data = json.loads(request.content)
        assert data['model'] == 'supplier-alias'
        assert data['output_format'] == 'gif'
        assert data['quality'] == '1k'
        assert data['size'] == '1024x1024'
        assert data['n'] == 1
        assert data['frame_count'] == 8 and data['frame_duration_ms'] == 250
        assert 'seamless loop' in data['prompt'] and '8 frames' in data['prompt'] and '250 milliseconds' in data['prompt']
        return httpx.Response(200, json={'data':[{'b64_json':base64.b64encode(gif_bytes()).decode()}]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('services.image_generation.gateway.httpx.AsyncClient',
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    images = await generate_for_sora_consistency({'base_traits':'A ball bounces.'},base_url='https://custom.example/proxy/v1',
        api_key='test',model='supplier-alias',resolution=selection.provider_size,quality=selection.provider_quality,
        output_format=selection.output_format,frame_count=selection.frame_count,frame_duration_ms=selection.frame_duration_ms)
    assert base64.b64decode(images[0].b64_json).startswith(b'GIF')


async def test_gif_edit_upload_sends_frame_options_as_multipart_fields(monkeypatch):
    async def handler(request):
        assert request.url.path == '/v1/images/edits'
        message=BytesParser(policy=policy.default).parsebytes(
            b'Content-Type: '+request.headers['content-type'].encode()+b'\r\n\r\n'+request.content)
        fields={part.get_param('name',header='content-disposition'):part.get_content()
            for part in message.iter_parts() if not part.get_filename()}
        assert fields['frame_count']=='4'
        assert fields['frame_duration_ms']=='100'
        assert fields['output_format']=='gif'
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(gif_bytes()).decode()}]})
    real_client=httpx.AsyncClient
    monkeypatch.setattr('services.image_generation.gateway.httpx.AsyncClient',
        lambda **kwargs:real_client(**kwargs,transport=httpx.MockTransport(handler)))
    reference='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nreference').decode()
    await generate_for_sora_consistency({'base_traits':'A ball bounces.'},base_url='https://custom.example/v1',
        api_key='test',output_format='gif',frame_count=4,frame_duration_ms=100,reference_images=[reference])


def test_gif_agent_facts_use_frames_instead_of_video_duration():
    from prompts.experience import opening_message
    message=opening_message(mode='agent',task_type='image',prompt='A ball bounces.',scene_id=None,
        asset_id=1,aspect_ratio='1:1',duration=5,output_format='gif',frame_count=9,frame_duration_ms=200)
    assert 'frame_count' in message and 'frame_duration_ms' in message
    assert '"duration"' not in message


@pytest.mark.parametrize('clarity', ['2K', '4K'])
def test_gif_rejects_unsupported_large_resolution_requests(clarity):
    with pytest.raises(HTTPException, match='清晰度'):
        validate_selection('gpt_image_2_6', clarity=clarity, aspect_ratio='1:1', output_format='gif', generation_count=1)


@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_gif_request_contains_format_motion_loop_and_actual_frame_parameters(monkeypatch, language):
    generate = AsyncMock(return_value=[])
    monkeypatch.setattr('services.reference.generator.generate_images', generate)
    prompt = 'A cat walks past the window.'
    await generate_for_sora_consistency({'base_traits': prompt}, base_url='https://provider.example/v1',
        api_key='test', model='gpt-image-2.6-flare', output_format='gif', frame_count=4, frame_duration_ms=100, prompt_language=language)
    sent = generate.await_args.kwargs
    assert sent['output_format'] == 'gif'
    assert sent['prompt'].startswith(prompt + '\n\n')
    assert ('连续运动' if language == 'zh' else 'continuous motion') in sent['prompt']
    assert ('循环播放' if language == 'zh' else 'seamless loop') in sent['prompt']
    assert ('4 帧' if language == 'zh' else '4 frames') in sent['prompt']
    assert ('100 毫秒' if language == 'zh' else '100 milliseconds') in sent['prompt']
    assert sent['extra_body'] == {'frame_count':4,'frame_duration_ms':100}
    assert render_gif_prompt(prompt, frame_count=4, frame_duration_ms=100, language=language) == sent['prompt']
    await generate_for_sora_consistency({'base_traits': prompt}, base_url='https://provider.example/v1',
        api_key='test', output_format='png', prompt_language=language)
    assert generate.await_args.kwargs['prompt'] == prompt
    assert generate.await_args.kwargs['output_format'] == 'png'
    assert generate.await_args.kwargs['extra_body'] == {}


@pytest.mark.parametrize('transport', ['base64', 'url'])
@pytest.mark.parametrize('actual_format', ['gif', 'png'])
async def test_saved_format_follows_actual_bytes_and_preserves_gif_frames(monkeypatch, tmp_path, transport, actual_format):
    monkeypatch.setattr('services.oss.oss', SimpleNamespace(enabled=False))
    original = gif_bytes() if actual_format == 'gif' else b'\x89PNG\r\n\x1a\npng-fallback'
    monkeypatch.setattr('services.reference.handler.settings.MEDIA_PATH', str(tmp_path))
    async def handler(request):
        return httpx.Response(200, content=original, headers={'content-type': 'image/gif'})
    real_client = httpx.AsyncClient
    monkeypatch.setattr('services.reference.handler.httpx.AsyncClient',
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    generated = SimpleNamespace(url='https://cdn.example/misleading.gif' if transport == 'url' else None,
        b64_json=base64.b64encode(original).decode() if transport == 'base64' else None)
    result = await _persist_generated_image(generated, 123, '_test')
    assert result == f'/media/assets/123_test.{actual_format}'
    saved = (tmp_path / 'assets' / f'123_test.{actual_format}').read_bytes()
    assert saved == original
    assert _content_type_for('.' + actual_format) == 'image/' + actual_format
    if actual_format == 'gif':
        decoded, animation = cv2.imdecodeanimation(np.frombuffer(saved, np.uint8))
        assert decoded and len(animation.frames) == 2
        assert (tmp_path / 'assets' / 'derivatives' / '123_test-thumbnail.webp').exists()


async def test_oss_upload_uses_original_gif_bytes_and_correct_mime(monkeypatch):
    original = gif_bytes()
    upload = AsyncMock()
    monkeypatch.setattr('services.oss.oss', SimpleNamespace(enabled=True, put_bytes=upload))
    monkeypatch.setattr('services.oss.make_upload_key', lambda *args: 'uploads/result.gif')
    monkeypatch.setattr('services.reference.handler.ensure_image_derivatives', AsyncMock())
    result = await _persist_generated_image(SimpleNamespace(url=None, b64_json=base64.b64encode(original).decode()), 123, '')
    assert result == 'uploads/result.gif'
    upload.assert_awaited_once_with('uploads/result.gif', original, 'image/gif')
