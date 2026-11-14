from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from auth.deps import AuthContext
from config import settings
from controllers.chapter_export import chapter_exports
from models.ai_task import AiTask
from models.chapter_export import ChapterExport
from models.config import AiModelConfig
from models.scene import Scene
from models.video import Video
from schemas.video_export import ExportEnhanceIn
from services.ai_task_executor import ai_task_executor
from services.video_enhancement.contract import ENHANCEMENT_PRESET
from services.video_enhancement.handler import EnhanceExportHandler
from services.video_enhancement.media import export_media, file_digest
from test.test_services.test_skill_workflow import enabled_project
from test.test_services.test_video_enhancement_media import fixture_video


@pytest.mark.asyncio
async def test_single_video_preparation_does_not_require_other_shots_and_preserves_original_bytes(tmp_path, monkeypatch, client):
    novel, chapter, _ = await enabled_project()
    monkeypatch.setattr(settings,'MEDIA_PATH',str(tmp_path/'media'))
    monkeypatch.setattr(settings,'CHAPTER_EXPORT_PATH',str(tmp_path/'private'))
    path=tmp_path/'media'/'clip.mp4';path.parent.mkdir()
    fixture_video(path,size='864x496')
    scene=await Scene.create(chapter=chapter,sequence=1)
    await Scene.create(chapter=chapter,sequence=2)  # This shot has no video yet.
    video=await Video.create(scene=scene,model_type=1,status=3,url='/media/clip.mp4')
    import asyncio
    (source,task),(repeated,replayed)=await asyncio.gather(chapter_exports.prepare_video(video.id,AuthContext()),chapter_exports.prepare_video(video.id,AuthContext()))
    assert source.id==repeated.id and task.id==replayed.id
    assert source.source_video_id==video.id and len(source.manifest)==1
    await ai_task_executor.run(task)
    await source.refresh_from_db();await task.refresh_from_db()
    assert task.status==3,task.error_message
    assert source.source_sha256==file_digest(path)
    assert file_digest(export_media.local_path(source.source_media_ref))==file_digest(path)
    assert (await Video.get(id=video.id)).url=='/media/clip.mp4'
    response = (await client.post(f'/api/video/exports/video/{video.id}')).json()
    assert response['code'] == 0 and response['data']['export_id'] == source.id
    history = (await client.get(f'/api/video/exports/video/{video.id}')).json()
    assert history['code'] == 0 and history['data'][0]['source_video_id'] == video.id
    config=await AiModelConfig.create(task_type=8,name='MediaKit',is_active=True,api_key='test-key',**ENHANCEMENT_PRESET)
    quote=await chapter_exports.quote(source,config.id,AuthContext())
    request=ExportEnhanceIn(model_config_id=config.id,source_sha256=quote['source_sha256'],quote_version=quote['quote_version'])
    first,first_task=await chapter_exports.enhance(source.id,request,AuthContext())
    second,second_task=await chapter_exports.enhance(source.id,request,AuthContext())
    assert first.id==second.id and first_task.id==second_task.id
    assert first.source_video_id==video.id
    assert await AiTask.filter(task_type=8).count()==1
    with pytest.raises(ValueError):
        await chapter_exports.quote(first,config.id,AuthContext())
    with pytest.raises(ValueError):
        await chapter_exports.enhance(first.id,request,AuthContext())
    blocked_quote = (await client.get(f'/api/video/exports/{first.id}/quote?model_config_id={config.id}')).json()
    assert blocked_quote['code'] == 400
    blocked_submit = (await client.post(f'/api/video/exports/{first.id}/enhance', json=request.model_dump())).json()
    assert blocked_submit['code'] == 400
    assert await AiTask.filter(task_type=8).count()==1


@pytest.mark.asyncio
@pytest.mark.parametrize('size',['1920x1080','1080x1920'])
async def test_actual_1080p_video_can_be_prepared_but_same_resolution_is_rejected(tmp_path, monkeypatch, size):
    _, chapter, _=await enabled_project()
    scene=await Scene.create(chapter=chapter,sequence=1)
    path=tmp_path/'hd.mp4';fixture_video(path,size=size)
    video=await Video.create(scene=scene,model_type=1,status=3,url='/media/hd.mp4',metadata={'resolution':'480p'})
    @asynccontextmanager
    async def materialize(_ref):yield path
    monkeypatch.setattr(export_media,'materialize',materialize)
    source,task=await chapter_exports.prepare_video(video.id,AuthContext())
    await ai_task_executor.run(task)
    await source.refresh_from_db()
    config=await AiModelConfig.create(task_type=8,name='MediaKit',is_active=True,api_key='test-key',**ENHANCEMENT_PRESET)
    with pytest.raises(ValueError):
        await chapter_exports.quote(source,config.id,AuthContext(),'1080p')
    quote=await chapter_exports.quote(source,config.id,AuthContext(),'2k')
    assert quote['recipe']['resolution']=='2k'
    assert await AiTask.filter(task_type=8).count()==0


@pytest.mark.asyncio
async def test_queued_1080p_task_cannot_bypass_server_upscale_guard():
    from test.test_services.test_video_enhancement_execution import pending_export
    task,export,_=await pending_export()
    export.source_probe={**export.source_probe,'width':1920,'height':1080}
    await export.save()
    with patch('services.video_enhancement.provider.MediaKitClient.submit',AsyncMock()) as submit:
        with pytest.raises(ValueError):
            await EnhanceExportHandler().execute(task.request_params)
        submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_episode_source_at_1080p_cannot_be_enhanced_even_with_a_forged_resolution_label():
    novel,chapter,_=await enabled_project()
    config=await AiModelConfig.create(task_type=8,name='MediaKit',is_active=True,api_key='test-key',**ENHANCEMENT_PRESET)
    source=await ChapterExport.create(novel_id=novel.id,chapter_id=chapter.id,identity_key='a'*64,source_version='b'*64,
        source_sha256='c'*64,source_media_ref='/media/exports/1/source.mp4',
        source_probe={'width':1920,'height':1080,'duration':'5','fps':'24'})
    with pytest.raises(ValueError):
        await chapter_exports.quote(source,config.id,AuthContext())
    assert await AiTask.filter(task_type=8).count()==0


@pytest.mark.asyncio
async def test_explicit_retry_creates_new_enhancement_attempt_and_keeps_old_receipts(tmp_path, monkeypatch):
    from services.video_enhancement.media import inspect_media
    novel, chapter, _ = await enabled_project()
    path = tmp_path / 'source.mp4'
    fixture_video(path, size='864x496')
    @asynccontextmanager
    async def materialize(_):
        yield path
    monkeypatch.setattr(export_media, 'materialize', materialize)
    source = await ChapterExport.create(novel_id=novel.id, chapter_id=chapter.id,
        identity_key='a' * 64, source_version='b' * 64, source_sha256=file_digest(path),
        source_media_ref='https://media.example/source.mp4', source_probe=inspect_media(path).model_dump(mode='json'))
    config = await AiModelConfig.create(task_type=8, name='MediaKit', is_active=True, api_key='test', **ENHANCEMENT_PRESET)
    quote = await chapter_exports.quote(source, config.id, AuthContext())
    request = ExportEnhanceIn(model_config_id=config.id, source_sha256=quote['source_sha256'], quote_version=quote['quote_version'])
    old, old_task = await chapter_exports.enhance(source.id, request, AuthContext())
    old_identity = old.identity_key
    await AiTask.filter(id=old_task.id).update(status=4, stage='needs_review')
    old.provider_task_id = 'old-provider-task'
    await old.save(update_fields=['provider_task_id'])
    fresh, task = await chapter_exports.enhance(source.id, request, AuthContext())
    assert fresh.id != old.id and task.id != old_task.id
    assert task.request_params['provider_client_token'] != old_identity
    await old.refresh_from_db()
    assert old.provider_task_id == 'old-provider-task' and old.identity_key != fresh.identity_key
    repeated, repeated_task = await chapter_exports.enhance(source.id, request, AuthContext())
    assert repeated.id == fresh.id and repeated_task.id == task.id
    assert await ChapterExport.filter(parent_export_id=source.id).count() == 2
