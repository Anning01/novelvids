from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from models.chapter_export import ChapterExport
from models.scene import Scene
from models.video import Video
from models.ai_task import AiTask
from controllers.chapter_export import chapter_exports
from services.video_enhancement.sources import freeze_chapter
from services.video_enhancement.media import export_media
from test.test_services.test_skill_workflow import enabled_project


@pytest.mark.asyncio
async def test_preparation_freezes_only_selected_successful_videos_and_reuses_task(tmp_path, monkeypatch):
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1)
    chosen = await Video.create(scene=scene, model_type=3, status=3, url='/media/selected.mp4')
    await Video.create(scene=scene, model_type=3, status=3, url='/media/unselected.mp4')
    scene.metadata = {'current_video_id': chosen.id}
    await scene.save()
    path = tmp_path/'selected.mp4'
    path.write_bytes(b'frozen selected video')
    @asynccontextmanager
    async def materialize(ref):
        assert ref == '/media/selected.mp4'
        yield path
    monkeypatch.setattr(export_media, 'materialize', materialize)
    export, task = await chapter_exports.prepare(chapter.id, AuthContext())
    repeated, replay = await chapter_exports.prepare(chapter.id, AuthContext())
    assert export.id == repeated.id and task.id == replay.id
    assert export.manifest[0]['video_id'] == chosen.id
    assert await AiTask.filter(task_type=4).count() == 1
    assert not export.source_media_ref
    assert task.request_params['novel_id'] == novel.id


@pytest.mark.asyncio
async def test_missing_selected_video_cannot_fall_back_to_an_older_success(tmp_path, monkeypatch):
    _, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, metadata={'current_video_id':999})
    await Video.create(scene=scene, model_type=3, status=3, url='/media/older.mp4')
    with pytest.raises(ValueError, match='全部完成|complete'):
        await freeze_chapter(chapter.id)
    assert await ChapterExport.all().count() == 0


@pytest.mark.asyncio
async def test_content_changed_at_same_reference_creates_a_new_source(tmp_path, monkeypatch):
    _, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1)
    await Video.create(scene=scene, model_type=3, status=3, url='/media/selected.mp4')
    path=tmp_path/'source.mp4'
    path.write_bytes(b'first')
    @asynccontextmanager
    async def materialize(_ref):yield path
    monkeypatch.setattr(export_media,'materialize',materialize)
    first, _=await chapter_exports.prepare(chapter.id,AuthContext())
    path.write_bytes(b'second')
    second, _=await chapter_exports.prepare(chapter.id,AuthContext())
    assert first.source_version != second.source_version
    assert first.id != second.id


@pytest.mark.asyncio
async def test_old_source_version_is_rejected_before_task_admission():
    _, chapter, _ = await enabled_project()
    with patch('controllers.chapter_export.freeze_chapter',AsyncMock(return_value=([{'video_id':1}], 'a'*64))):
        with pytest.raises(HTTPException) as error:
            await chapter_exports.prepare(chapter.id,AuthContext(),expected_version='b'*64)
    assert error.value.status_code == 409
    assert await ChapterExport.all().count() == 0


@pytest.mark.asyncio
async def test_preparation_runs_through_existing_assistant_without_llm_or_media_provider():
    _, chapter, _=await enabled_project()
    from services.ai_task_executor import ai_task_executor
    scene = await Scene.create(chapter=chapter, sequence=1)
    video = await Video.create(scene=scene, model_type=3, status=3, url='/media/fixture.mp4')
    manifest = [{'scene_id':scene.id, 'sequence':1, 'video_id':video.id, 'ref':video.url, 'sha256':'c'*64}]
    with patch('controllers.chapter_export.freeze_chapter',AsyncMock(return_value=(manifest, 'a'*64))):
        export,task=await chapter_exports.prepare(chapter.id,AuthContext())
    result={'ref':'/media/exports/source.mp4','sha256':'b'*64,'probe':{'duration':'6','width':864,'height':496,'fps':'24'}}
    with patch.object(export_media,'compose',AsyncMock(return_value=result)) as compose:
        await ai_task_executor.run(task)
        await ai_task_executor.run(task)
    await task.refresh_from_db();await export.refresh_from_db()
    assert task.status == 3,task.error_message
    assert task.request_params['conversation_id']
    assert export.media_ref == result['ref']
    assert export.source_sha256 == result['sha256']
    compose.assert_awaited_once()


@pytest.mark.asyncio
async def test_selection_changed_before_admission_rejects_the_stale_manifest():
    _, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1)
    video = await Video.create(scene=scene, model_type=3, status=3, url='/media/current.mp4')
    manifest = [{'scene_id':scene.id, 'sequence':1, 'video_id':video.id + 1, 'sha256':'c'*64}]
    with patch('controllers.chapter_export.freeze_chapter', AsyncMock(return_value=(manifest, 'a'*64))):
        with pytest.raises(HTTPException) as error:
            await chapter_exports.prepare(chapter.id, AuthContext())
    assert error.value.status_code == 409
    assert await ChapterExport.all().count() == 0


@pytest.mark.asyncio
async def test_enhancement_admission_has_no_credentials_and_reuses_content_operation(tmp_path,monkeypatch):
    from models.config import AiModelConfig
    from schemas.video_export import ExportEnhanceIn
    from test.test_services.test_video_enhancement_billing import PRICING
    from services.video_enhancement.contract import EnhancementOptions
    from services.video_enhancement.media import file_digest
    _,chapter,_=await enabled_project()
    path=tmp_path/'source.mp4';path.write_bytes(b'approved-source')
    @asynccontextmanager
    async def materialize(_ref):yield path
    monkeypatch.setattr(export_media,'materialize',materialize)
    source=await ChapterExport.create(novel_id=chapter.novel_id,chapter_id=chapter.id,identity_key='a'*64,
        source_version='b'*64,source_sha256=file_digest(path),source_media_ref='/media/source.mp4',
        source_probe={'duration':'5','width':864,'height':496,'fps':'24'})
    config=await AiModelConfig.create(name='processing',task_type=8,model='enhance-video-generative',is_active=True,
        api_key='never-persist-this',base_url='https://mediakit.example',api_protocol='volcengine_mediakit',pricing=PRICING,
        processing_options=EnhancementOptions(media_base_url='https://my-media.example').model_dump(mode='json'))
    quote=await chapter_exports.quote(source,config.id,AuthContext())
    request=ExportEnhanceIn(model_config_id=config.id,source_sha256=quote['source_sha256'],quote_version=quote['quote_version'])
    export,task=await chapter_exports.enhance(source.id,request,AuthContext())
    again,replay=await chapter_exports.enhance(source.id,request,AuthContext())
    assert export.id==again.id and task.id==replay.id
    assert 'never-persist-this' not in str(task.request_params)
    export.media_ref = '/media/exports/ready.mp4'
    await export.save()
    await AiTask.filter(id=task.id).update(status=3)
    reusable_quote = await chapter_exports.quote(source,config.id,AuthContext())
    assert reusable_quote['amount'] == '0' and reusable_quote['reused_export_id'] == export.id
    # Keep the pre-release identity usable only for its own chapter.
    from services.video_enhancement.media import digest
    export.identity_key = digest(['enhance', source.novel_id, None, source.source_sha256, quote['recipe']])
    await export.save()
    assert (await chapter_exports.quote(source,config.id,AuthContext()))['reused_export_id'] == export.id
    from models.chapter import Chapter
    other_chapter = await Chapter.create(novel_id=chapter.novel_id, number=2, name='Same clip, other episode', content='Fixture')
    other_source = await ChapterExport.create(novel_id=chapter.novel_id, chapter_id=other_chapter.id,
        identity_key='d'*64, source_version='e'*64, source_sha256=source.source_sha256,
        source_media_ref=source.source_media_ref, source_probe=source.source_probe)
    other_quote = await chapter_exports.quote(other_source,config.id,AuthContext())
    assert other_quote['reused_export_id'] is None and other_quote['amount'] == '0.416667'
    assert other_quote['quote_version'] != quote['quote_version']
    with pytest.raises(HTTPException) as wrong_chapter:
        await chapter_exports.enhance(other_source.id,request,AuthContext())
    assert wrong_chapter.value.status_code == 409
    other_request = ExportEnhanceIn(model_config_id=config.id,source_sha256=other_quote['source_sha256'],quote_version=other_quote['quote_version'])
    second, second_task = await chapter_exports.enhance(other_source.id,other_request,AuthContext())
    assert second.id != export.id and second.chapter_id == other_chapter.id
    assert second_task.id != task.id
    await AiModelConfig.filter(id=config.id).update(pricing={**PRICING,'discount':2})
    with pytest.raises(HTTPException) as error:await chapter_exports.enhance(source.id,request,AuthContext())
    assert error.value.status_code==409


@pytest.mark.asyncio
async def test_missing_model_configuration_cannot_prepare_paid_enhancement():
    _,chapter,_=await enabled_project()
    source=await ChapterExport.create(novel_id=chapter.novel_id,chapter_id=chapter.id,identity_key='a'*64,
        source_version='b'*64,source_sha256='c'*64,source_media_ref='/media/source.mp4',
        source_probe={'duration':'5','width':864,'height':496,'fps':'24'})
    with pytest.raises(HTTPException):await chapter_exports.quote(source,123,AuthContext())
    assert await AiTask.filter(task_type=8).count()==0
