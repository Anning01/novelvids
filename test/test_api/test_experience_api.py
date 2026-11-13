"""Clip contexts never fabricate media and reuse existing authorization/production."""
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from config import settings
from auth.deps import AuthContext
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.asset import Asset
from models.config import AiModelConfig
from schemas.experience import ExperienceGenerateIn
from services.experience import create_clip, clip_session, start_clip
from test.test_services.test_skill_workflow import enabled_project


@pytest.fixture
async def configured(monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)
    await enabled_project()
    video = await AiModelConfig.create(name='Configured video', model='video', task_type=4,
        api_key='test', base_url='https://example.test', video_model_type='seedance_2', api_protocol='volcengine_ark', is_active=True, pricing={'type':'video','currency':'CNY','billing_unit':'second','prices':{'720p':0.1}})
    image = await AiModelConfig.create(name='Configured image', model='image', task_type=2,
        api_key='test', base_url='https://example.test', image_model_type='seedream_5_lite', api_protocol='volcengine_ark', is_active=True, pricing={'type':'image','currency':'CNY','prices':{'2K':0.2}})
    return video, image


def payload(model_id, **changes):
    return ExperienceGenerateIn(request_id=uuid4(), model_config_id=model_id, prompt='雨夜里，一只猫走过街角。',
        aspect_ratio='16:9', resolution='720p', duration=5, **changes)


@pytest.mark.asyncio
async def test_create_is_durable_idempotent_and_contains_no_fake_result(configured):
    video, _ = configured
    request = payload(video.id)
    first = await create_clip(request, AuthContext())
    again = await create_clip(request, AuthContext())
    assert first == again
    assert 'media_url' not in first and 'thumbnail_url' not in first
    assert first['model_name'] == video.name
    assert await Chapter.filter(novel_id=first['project_id']).count() == 1
    assert await Scene.filter(chapter_id=first['chapter_id']).count() == 1
    assert (await Scene.get(id=first['scene_id'])).prompt == request.prompt
    with pytest.raises(HTTPException) as error:
        await create_clip(request.model_copy(update={'prompt': 'Different idea'}), AuthContext())
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_reference_mode_links_real_reference_asset_to_clip(configured):
    video, image = configured
    result = await create_clip(payload(video.id, mode='reference'), AuthContext())
    scene = await Scene.get(id=result['scene_id'])
    asset = await Asset.get(id=result['asset_id'])
    assert await scene.assets.filter(id=asset.id).exists()
    assert asset.metadata['aspect_ratio'] == '16:9'
    assert result['image_model_config_id'] == image.id
    assert asset.main_image is None


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,operation', [('agent', None), ('reference', 'image')])
async def test_initial_submission_uses_existing_agent_intents_and_stable_request(configured, mode, operation):
    video, _ = configured
    result = await create_clip(payload(video.id, mode=mode), AuthContext())
    with patch('services.experience.creation_agent_controller.submit', new=AsyncMock(return_value='task')) as submit:
        assert await start_clip(result['project_id'], AuthContext()) == 'task'
        first = submit.call_args.args[1]
        await start_clip(result['project_id'], AuthContext())
        assert submit.call_args.args[1].request_id == first.request_id
    assert first.chapter_id == result['chapter_id']
    if operation:
        assert first.production_intents[0].operation == operation
        if operation == 'video':
            assert first.production_intents[0].video_options.aspect_ratio == '16:9'
    else:
        assert first.production_intents == []
    assert 'untrusted_task_facts' in first.message
    assert '雨夜里' in first.message


@pytest.mark.asyncio
async def test_unavailable_model_does_not_create_context(configured):
    before = await Novel.all().count()
    with pytest.raises(HTTPException):
        await create_clip(payload(999999), AuthContext())
    assert await Novel.all().count() == before


@pytest.mark.asyncio
async def test_real_image_selection_keeps_requested_ratio_and_model(configured):
    _, image = configured
    request = payload(image.id, task_type='image', mode='direct').model_copy(update={'resolution': '2K', 'aspect_ratio': '1:1'})
    result = await create_clip(request, AuthContext())
    asset = await Asset.get(id=result['asset_id'])
    assert asset.metadata['aspect_ratio'] == '1:1'
    assert asset.metadata['resolution'] == '2K'
    assert asset.base_traits == request.prompt
    assert result['model_config_id'] == image.id


async def test_gif_clip_preserves_frame_options_and_queued_request(configured):
    from controllers.asset import asset_controller
    from models.ai_task import AiTask
    image = await AiModelConfig.create(name='GIF model', model='supplier-alias', task_type=2,
        api_key='test', base_url='https://provider.example/v1', image_model_type='gpt_image_2_6',
        api_protocol='openai_compatible', is_active=True,
        pricing={'type':'image','currency':'CNY','prices':{'1K':0.1,'2K':0.2,'4K':0.4}})
    request = payload(image.id, task_type='image', mode='direct', output_format='gif',frame_count=4,frame_duration_ms=100).model_copy(update={'resolution':'1K'})
    session = await create_clip(request, AuthContext())
    assert session['output_format'] == 'gif'
    assert session['frame_count'] == 4
    assert session['frame_duration_ms'] == 100
    asset = await Asset.get(id=session['asset_id'])
    assert asset.metadata['output_format'] == 'gif'
    assert asset.metadata['frame_count'] == 4
    assert asset.metadata['frame_duration_ms'] == 100
    task = await asset_controller.reference(asset.id)
    task = await AiTask.get(id=task.id)
    assert task.request_params['output_format'] == 'gif'
    assert task.request_params['frame_count'] == 4
    assert task.request_params['frame_duration_ms'] == 100
    assert task.request_params['quality'] == '1k'


async def test_non_gif_models_reject_gif_before_creating_a_project(configured):
    _, image = configured
    before = await Novel.all().count()
    with pytest.raises(HTTPException, match='格式'):
        await create_clip(payload(image.id, task_type='image', output_format='gif').model_copy(update={'resolution':'2K'}), AuthContext())
    assert await Novel.all().count() == before


async def test_legacy_png_requests_keep_their_existing_idempotency_hash(configured):
    import hashlib
    video, _ = configured
    request = payload(video.id)
    session = await create_clip(request, AuthContext())
    project = await Novel.get(id=session['project_id'])
    old_serialized = request.model_dump_json(exclude={'output_format','reference_binding','frame_count','frame_duration_ms'})
    assert project.creation_payload_hash == hashlib.sha256(old_serialized.encode()).hexdigest()
    settings_data = __import__('json').loads(project.project_setting)
    settings_data.pop('output_format', None)
    project.project_setting = __import__('json').dumps(settings_data)
    await project.save(update_fields=['project_setting'])
    assert (await clip_session(project.id, AuthContext()))['output_format'] == 'png'
    assert (await create_clip(request, AuthContext()))['project_id'] == project.id


async def test_existing_gif_drafts_restore_frame_defaults_without_rewriting_history(configured):
    import hashlib,json
    from tortoise import Tortoise
    from controllers.asset import asset_controller
    image=await AiModelConfig.create(name='Legacy GIF',model='supplier-alias',task_type=2,
        base_url='https://provider.example/v1',api_key='test',api_protocol='openai_compatible',
        image_model_type='gpt_image_2_6',is_active=True,
        pricing={'type':'image','currency':'CNY','prices':{'1K':0.1,'2K':0.2,'4K':0.4}})
    request=payload(image.id,task_type='image',output_format='gif').model_copy(update={'resolution':'1K'})
    result=await create_clip(request,AuthContext())
    project=await Novel.get(id=result['project_id'])
    old_body=request.model_dump_json(exclude={'frame_count','frame_duration_ms','reference_binding'})
    assert project.creation_payload_hash==hashlib.sha256(old_body.encode()).hexdigest()
    stored=json.loads(project.project_setting)
    stored.pop('frame_count');stored.pop('frame_duration_ms')
    project.project_setting=json.dumps(stored)
    await project.save(update_fields=['project_setting'])
    asset=await Asset.get(id=result['asset_id'])
    metadata={key:value for key,value in asset.metadata.items() if key not in {'frame_count','frame_duration_ms'}}
    metadata['gif_duration']=5
    asset.metadata=metadata
    await asset.save(update_fields=['metadata'])
    for _ in range(2):await Tortoise.generate_schemas(safe=True)
    restored=await clip_session(project.id,AuthContext())
    assert (restored['frame_count'],restored['frame_duration_ms'])==(9,200)
    assert (await create_clip(request,AuthContext()))['project_id']==project.id
    task=await asset_controller.reference(asset.id)
    assert (task.request_params['frame_count'],task.request_params['frame_duration_ms'])==(9,200)
    await asset.refresh_from_db()
    assert asset.metadata==metadata


@pytest.mark.asyncio
async def test_non_clip_projects_cannot_be_opened_as_clip(configured):
    project = await Novel.create(name='Series')
    with pytest.raises(HTTPException) as error:
        await clip_session(project.id, AuthContext())
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_showcase_empty_means_empty_and_legacy_fake_payload_is_rejected(client, configured):
    response = await client.get('/api/experience/showcase')
    assert response.json()['data'] == []
    rejected = await client.post('/api/experience/generate', json={'model_name': 'invented', 'prompt': 'hello'})
    assert rejected.json().get('code') != 0
    stale = await client.post('/api/experience/save-to-library', json={'media_url': '/media/videos/18.mp4'})
    assert stale.json().get('code') != 0


@pytest.mark.asyncio
async def test_http_create_and_restore_return_the_same_context(client, configured):
    video, _ = configured
    response = await client.post('/api/experience/generate', json=payload(video.id).model_dump(mode='json'))
    assert response.json()['code'] == 0, response.text
    session = response.json()['data']
    restored = await client.get(f'/api/experience/sessions/{session["project_id"]}')
    assert restored.json()['data'] == session
    listed = await client.get('/api/experience/sessions')
    assert session['project_id'] in [item['project_id'] for item in listed.json()['data']]


@pytest.mark.asyncio
async def test_start_persists_one_real_agent_task_and_replays_without_duplicate(configured):
    video, _ = configured
    result = await create_clip(payload(video.id, mode='direct'), AuthContext())
    task = await start_clip(result['project_id'], AuthContext())
    replay = await start_clip(result['project_id'], AuthContext())
    assert task.id == replay.id
    from models.creation_agent import AgentMessage
    message = await AgentMessage.get(task_id=task.id, role='user')
    assert task.task_type == 4
    assert task.request_params['video_request']['model_config_id'] == video.id
    assert task.request_params['video_request']['scene_id'] == result['scene_id']
    assert (await Scene.get(id=result['scene_id'])).prompt == result['prompt']
    assert message.conversation_id == (await clip_session(result['project_id'], AuthContext()))['conversation_id']


@pytest.mark.asyncio
async def test_uploaded_references_survive_existing_explicit_reference_filter(configured):
    from schemas.video import VideoReferenceMedia
    from services.video.reference_media import select_referenced_media
    video, _ = configured
    reference = VideoReferenceMedia(type='image', url='/media/reference.png', name='我的参考')
    request = payload(video.id, mode='direct').model_copy(update={'reference_media': [reference]})
    result = await create_clip(request, AuthContext())
    scene = await Scene.get(id=result['scene_id'])
    assert scene.prompt.startswith(request.prompt)
    assert select_referenced_media(scene.prompt, [reference]) == [reference]


@pytest.mark.asyncio
async def test_session_denies_cross_team_access(configured, monkeypatch):
    from types import SimpleNamespace
    video, _ = configured
    result = await create_clip(payload(video.id), AuthContext())
    await Novel.filter(id=result['project_id']).update(team_id=101)
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    with pytest.raises(HTTPException) as error:
        await clip_session(result['project_id'], AuthContext(user=SimpleNamespace(id=1), team_id=202))
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_create_or_start_clip(client, configured, monkeypatch):
    from types import SimpleNamespace
    from main import app
    from auth.deps import get_auth_context
    video, _ = configured
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(user=SimpleNamespace(id=1), team_id=101, membership=SimpleNamespace(role='viewer'))
    try:
        response = await client.post('/api/experience/generate', json=payload(video.id).model_dump(mode='json'))
        assert response.json()['code'] == 403
        response = await client.post('/api/experience/sessions/1/start')
        assert response.json()['code'] == 403
    finally:
        app.dependency_overrides.pop(get_auth_context)


@pytest.mark.asyncio
async def test_showcase_uses_only_published_works_and_verified_media_routes(client, configured):
    from types import SimpleNamespace
    from models.portfolio import PortfolioWork
    project = await Novel.create(name='已公开作品')
    private = await Novel.create(name='私人草稿')
    await PortfolioWork.create(novel=project, title=project.name, status='public')
    await PortfolioWork.create(novel=private, title=private.name, status='private')
    detail = SimpleNamespace(title=project.name, cover_export_id=77, episodes=[SimpleNamespace(version=SimpleNamespace(id=78, duration=12.3, width=1920, height=1080))],
        episode_count=1, duration=12.3, category='短片', tags=[], description='', producer='创作者')
    with patch('api.experience.portfolio.detail', new=AsyncMock(return_value=detail)) as load:
        response = await client.get('/api/experience/showcase')
    load.assert_awaited_once_with(project.id)
    work = response.json()['data'][0]
    assert work['video_url'] == f'/api/portfolio/public/{project.id}/episodes/78/video'
    assert work['cover'] == f'/api/portfolio/public/{project.id}/episodes/78/cover'
    assert work['cover_width'] == 1920 and work['cover_height'] == 1080
    assert work['duration'] == '00:12'
    assert work['heat'] == ''


@pytest.mark.asyncio
async def test_direct_image_submission_keeps_verbatim_prompt_without_agent_dispatch(configured):
    _, image = configured
    request = payload(image.id, task_type='image', mode='direct').model_copy(update={'resolution':'2K'})
    result = await create_clip(request, AuthContext())
    assert result['scene_id'] is None
    with patch('services.experience.creation_agent_controller.submit', side_effect=AssertionError('Direct generation must not invoke a chat turn')):
        first = await start_clip(result['project_id'], AuthContext())
        replay = await start_clip(result['project_id'], AuthContext())
    assert first.id == replay.id
    assert first.task_type == 2
    assert first.request_params['model_config_id'] == image.id
    assert first.request_params['aspect_ratio'] == '16:9'
    assert (await Asset.get(id=result['asset_id'])).base_traits == request.prompt


@pytest.mark.asyncio
async def test_showcase_preview_matches_cover_episode_and_uses_its_actual_duration(client, configured):
    from types import SimpleNamespace
    from models.portfolio import PortfolioWork
    project = await Novel.create(name='多集公开作品')
    await PortfolioWork.create(novel=project, title=project.name, status='public')
    detail = SimpleNamespace(title=project.name, cover_export_id=22, episodes=[
        SimpleNamespace(version=SimpleNamespace(id=11, duration=60, width=1920, height=1080)),
        SimpleNamespace(version=SimpleNamespace(id=22, duration=94, width=1080, height=1920)),
    ], episode_count=2, duration=154, category='短剧', tags=[], description='真实介绍', producer='创作者')
    with patch('api.experience.portfolio.detail', new=AsyncMock(return_value=detail)):
        response = await client.get('/api/experience/showcase')
    work = response.json()['data'][0]
    assert work['cover'].endswith('/episodes/22/cover')
    assert work['video_url'].endswith('/episodes/22/video')
    assert work['duration'] == '01:34'
    assert work['cover_width'] == 1080 and work['cover_height'] == 1920


@pytest.mark.asyncio
async def test_named_references_bind_only_selected_mentions_and_keep_original_input(configured):
    from schemas.video import VideoReferenceMedia
    from services.video.reference_media import select_referenced_media
    video, _ = configured
    first=VideoReferenceMedia(type='image',url='/media/one.png',mention_name='图片1')
    second=VideoReferenceMedia(type='image',url='/media/two.png',mention_name='图片10')
    request=payload(video.id,mode='direct').model_copy(update={
        'reference_binding':'mentions', 'reference_media':[first,second],
        'prompt':'使用 @{图片10}，人物说：“图片1没有变化。”',
    })
    result=await create_clip(request,AuthContext())
    scene=await Scene.get(id=result['scene_id'])
    assert select_referenced_media(scene.prompt,[first,second]) == [second]
    assert '人物说：“图片1没有变化。”' in scene.prompt
    assert result['prompt'] == request.prompt
    no_mention=payload(video.id,mode='direct').model_copy(update={
        'reference_binding':'mentions', 'reference_media':[first], 'prompt':'只看雨中的街角。',
    })
    other=await create_clip(no_mention,AuthContext())
    assert select_referenced_media((await Scene.get(id=other['scene_id'])).prompt,[first]) == []


@pytest.mark.asyncio
async def test_legacy_reference_requests_keep_their_original_idempotency_hash(configured):
    import hashlib
    video, _ = configured
    request=payload(video.id)
    result=await create_clip(request,AuthContext())
    project=await Novel.get(id=result['project_id'])
    assert project.creation_payload_hash == hashlib.sha256(request.model_dump_json(exclude={'reference_binding', 'output_format','frame_count','frame_duration_ms'}).encode()).hexdigest()


def test_named_reference_contract_rejects_ambiguous_names_and_preserves_language():
    from pydantic import ValidationError
    from prompts.experience import render_named_references
    request=payload(1).model_dump(mode='json')
    request.update(reference_binding='mentions',reference_media=[
        {'type':'image','url':'/a','mention_name':'same'}, {'type':'image','url':'/b','mention_name':'same'},
    ])
    with pytest.raises(ValidationError,match='引用名称'):
        ExperienceGenerateIn.model_validate(request)
    assert render_named_references('Keep @{Alice} and 原文。',{'Alice':'@{reference}'}) == 'Keep @{reference} and 原文。'


async def test_seedream_55_quote_uses_requested_size_and_channel_discount(configured):
    from decimal import Decimal
    from services.experience_quote import clip_quote

    _, image = configured
    image.image_model_type = "seedream_5_5"
    image.api_protocol = "novelvids"
    image.pricing = {"type": "image", "billing_unit": "pixel_tier", "discount": 0.5,
                     "prices": {"low": .13, "high_capped": .23},
                     "input_image": {"first_free": 0, "price_per_image": .05}}
    await image.save()
    request = payload(image.id, task_type="image", mode="direct").model_copy(update={"resolution": "2K"})
    quote = await clip_quote(request, AuthContext())
    assert quote.allowed and quote.original_cost == Decimal(".23") and quote.estimated_cost == Decimal(".115")
