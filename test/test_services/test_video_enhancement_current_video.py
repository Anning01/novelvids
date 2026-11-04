from unittest.mock import AsyncMock, patch

import pytest

from auth.deps import AuthContext
from config import settings
from controllers.chapter_export import chapter_exports
from controllers.video import video_controller
from models.agent_operation import AgentOperation
from models.scene import Scene
from models.video import Video
from services.video_enhancement.current_video import apply_enhanced_video
from services.video_enhancement.media import export_media, file_digest
from services.video_enhancement.recovery import collect_export
from services.video_enhancement.sources import current_selection, freeze_chapter
from test.test_services.test_skill_workflow import enabled_project
from test.test_services.test_video_enhancement_billing import completed_export


async def ready_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path / 'private'))
    novel, chapter, _ = await enabled_project()
    scene = await Scene.create(chapter=chapter, sequence=1, metadata={'keep': 'user setting'})
    source = await Video.create(scene=scene, model_type=1, status=3, url='/media/original.mp4',
                                metadata={'resolution': '480p', 'width': 864, 'height': 496})
    scene.metadata = {**scene.metadata, 'current_video_id': source.id}
    await scene.save()
    task, export = await completed_export(novel_id=novel.id, chapter_id=chapter.id)
    task.status = 3
    await task.save()
    export.source_video_id = source.id
    export.parent_export_id = 999
    export.media_ref = f'/media/exports/{export.id}/1080p.mp4'
    export.output_probe = {'width': 1920, 'height': 1080, 'duration': '5', 'fps': '24'}
    path = export_media.local_path(export.media_ref)
    path.parent.mkdir(parents=True)
    path.write_bytes(b'verified enhanced fixture')
    export.media_sha256 = file_digest(path)
    await export.save()
    return scene, source, task, export


@pytest.mark.asyncio
async def test_completed_clip_replaces_current_selection_but_preserves_original_and_history(tmp_path, monkeypatch):
    scene, source, task, export = await ready_clip(tmp_path, monkeypatch)
    enhanced = await apply_enhanced_video(export)
    await scene.refresh_from_db(); await source.refresh_from_db()
    assert scene.metadata == {'keep': 'user setting', 'current_video_id': enhanced.id}
    assert source.url == '/media/original.mp4' and source.metadata['resolution'] == '480p'
    assert enhanced.metadata['resolution'] == '1080p' and enhanced.metadata['height'] == 1080
    assert enhanced.metadata['enhancement_source_video_id'] == source.id
    assert enhanced.metadata['provider_accounting'] == {'usage_reported': True, 'reported_seconds': 5}
    assert export_media.local_path(enhanced.url).read_bytes() == b'verified enhanced fixture'
    assert export_media.local_path(export.media_ref).is_file()
    assert (await current_selection(scene.chapter_id))[0]['video_id'] == enhanced.id
    manifest, _ = await freeze_chapter(scene.chapter_id)
    assert manifest[0]['ref'] == enhanced.url
    assert (await chapter_exports.describe(export))['applied_to_scene'] is True
    assert (await apply_enhanced_video(export)).id == enhanced.id
    assert await Video.filter(scene=scene).count() == 2
    assert await AgentOperation.filter(task=task, key='apply:enhanced_video').count() == 1


@pytest.mark.asyncio
async def test_recovery_does_not_override_a_user_who_restored_the_original(tmp_path, monkeypatch):
    scene, source, _, export = await ready_clip(tmp_path, monkeypatch)
    enhanced = await apply_enhanced_video(export)
    await video_controller.select_current(source.id)
    assert (await apply_enhanced_video(export)).id == enhanced.id
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == source.id
    assert (await chapter_exports.describe(export))['applied_to_scene'] is False
    assert (await chapter_exports.apply_video(export.id, AuthContext())).id == enhanced.id
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == enhanced.id
    assert await Video.filter(scene=scene).count() == 2


@pytest.mark.asyncio
async def test_a_newer_user_selection_is_preserved_until_explicitly_selecting_hd(tmp_path, monkeypatch):
    scene, _, _, export = await ready_clip(tmp_path, monkeypatch)
    newer = await Video.create(scene=scene, model_type=1, status=3, url='/media/new.mp4')
    await video_controller.select_current(newer.id)
    enhanced = await apply_enhanced_video(export)
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == newer.id
    assert enhanced.status == 3
    await chapter_exports.apply_video(export.id, AuthContext())
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == enhanced.id


@pytest.mark.asyncio
async def test_a_lower_resolution_completion_does_not_replace_a_higher_result(tmp_path, monkeypatch):
    scene, source, _, export = await ready_clip(tmp_path, monkeypatch)
    higher = await Video.create(scene=scene, model_type=1, status=3, url='/media/4k.mp4',
        metadata={'enhancement_source_video_id': source.id, 'width': 3840, 'height': 2160})
    await video_controller.select_current(higher.id)
    await apply_enhanced_video(export)
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == higher.id


@pytest.mark.asyncio
async def test_collector_applies_the_saved_clip_without_regenerating_or_double_billing(tmp_path, monkeypatch):
    scene, _, task, export = await ready_clip(tmp_path, monkeypatch)
    task.status = 2; await task.save()
    with patch('services.video_enhancement.provider.MediaKitClient.submit', AsyncMock()) as submit, \
         patch.object(export_media, 'save_enhanced', AsyncMock()) as save:
        await collect_export(export)
        await collect_export(export)
        submit.assert_not_awaited(); save.assert_not_awaited()
    from models.usage_record import ModelUsageRecord
    await scene.refresh_from_db(); await task.refresh_from_db()
    assert scene.metadata['current_video_id'] != export.source_video_id and task.status == 3
    assert await Video.filter(scene=scene).count() == 2
    assert await ModelUsageRecord.filter(ai_task_id=task.id).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [2, 4, 5])
async def test_unfinished_failed_or_cancelled_enhancement_never_replaces_a_video(tmp_path, monkeypatch, status):
    scene, source, task, export = await ready_clip(tmp_path, monkeypatch)
    task.status = status; await task.save()
    with pytest.raises(ValueError):
        await apply_enhanced_video(export)
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == source.id
    assert await Video.filter(scene=scene).count() == 1


@pytest.mark.asyncio
async def test_changed_saved_media_cannot_be_published_or_selected(tmp_path, monkeypatch):
    scene, source, _, export = await ready_clip(tmp_path, monkeypatch)
    export_media.local_path(export.media_ref).write_bytes(b'changed after validation')
    with pytest.raises(ValueError):
        await apply_enhanced_video(export)
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == source.id
    assert await Video.filter(scene=scene).count() == 1


@pytest.mark.asyncio
async def test_free_apply_endpoint_returns_an_ordinary_playable_video_without_a_new_task(tmp_path, monkeypatch, client):
    scene, source, _, export = await ready_clip(tmp_path, monkeypatch)
    from models.ai_task import AiTask
    count = await AiTask.all().count()
    response = (await client.post(f'/api/video/exports/{export.id}/apply')).json()
    assert response['code'] == 0 and response['data']['id'] != source.id
    assert response['data']['url'].startswith('/media/videos/enhanced-')
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == response['data']['id']
    assert await AiTask.all().count() == count


@pytest.mark.asyncio
async def test_concurrent_application_creates_only_one_video_version(tmp_path, monkeypatch):
    import asyncio
    scene, _, _, export = await ready_clip(tmp_path, monkeypatch)
    first, second = await asyncio.gather(apply_enhanced_video(export), apply_enhanced_video(export))
    assert first.id == second.id
    assert await Video.filter(scene=scene).count() == 2


@pytest.mark.asyncio
async def test_archived_scene_is_not_changed_and_can_select_hd_after_restoration(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    scene, _, _, export = await ready_clip(tmp_path, monkeypatch)
    await Scene.filter(id=scene.id).update(deleted_at=datetime.now(timezone.utc))
    assert await apply_enhanced_video(export) is None
    assert await Video.filter(scene_id=scene.id).count() == 1
    await Scene.with_deleted().filter(id=scene.id).update(deleted_at=None)
    enhanced = await apply_enhanced_video(export, select=True)
    await scene.refresh_from_db()
    assert scene.metadata['current_video_id'] == enhanced.id


@pytest.mark.asyncio
async def test_real_hd_clip_is_selected_and_used_for_chapter_composition(tmp_path, monkeypatch):
    from services.video.merge import VideoMerger
    from services.video_enhancement.media import inspect_media
    from test.test_services.test_video_enhancement_media import fixture_video
    scene, source, _, export = await ready_clip(tmp_path, monkeypatch)
    original = export_media.local_path(source.url)
    original.parent.mkdir(parents=True, exist_ok=True)
    fixture_video(original, size='864x496')
    hd = export_media.local_path(export.media_ref)
    fixture_video(hd, size='1920x1080')
    export.media_sha256 = file_digest(hd)
    export.output_probe = inspect_media(hd).model_dump(mode='json')
    export.provider_result['result']['duration'] = float(export.output_probe['duration'])
    await export.save()
    original_hash = file_digest(original)
    enhanced = await apply_enhanced_video(export)
    monkeypatch.setattr('controllers.video.video_merger', VideoMerger())
    result = await video_controller._compose_chapter(scene.chapter_id, strict=True)
    probe = inspect_media(export_media.local_path(result['merged_url']))
    assert (probe.width, probe.height) == (1920, 1080)
    assert file_digest(export_media.local_path(enhanced.url)) == file_digest(hd)
    assert file_digest(original) == original_hash
