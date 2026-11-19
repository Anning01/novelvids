import pytest

from config import settings
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.finished_episode import FinishedEpisodePublication
from models.media_deletion import MediaDeletion
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterEditDraft
from services.deleted_media import drain_media_deletions
from services.reference.dependencies import REFERENCE_KEY
from services.video_enhancement.media import export_media


def put(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'test-media')
    return path


@pytest.mark.asyncio
async def test_delete_episode_with_videos_and_finished_export(client, tmp_path, monkeypatch):
    root = tmp_path / 'media'
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(root))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path / 'private-exports'))
    project = await Novel.create(name='章节删除')
    chapter = await Chapter.create(novel=project, number=1, name='待删除', content='第一集')
    other = await Chapter.create(novel=project, number=2, name='保留', content='第二集')
    shot = await Scene.create(chapter=chapter, sequence=1)
    surviving_shot = await Scene.create(chapter=other, sequence=1)
    shared_file = put(root / 'videos' / 'shared.mp4')
    exclusive = put(root / 'videos' / 'exclusive.mp4')
    shared = await Asset.create(novel=project, asset_type=1, canonical_name='跨集角色', source_chapters=[1, 2])
    form = await AssetVariant.create(asset=shared, name='正装', chapter_numbers=[1, 2])
    owned = await Asset.create(novel=project, asset_type=3, canonical_name='本集道具', source_chapters=[1], is_global=False)
    await shot.assets.add(shared, owned)
    await surviving_shot.assets.add(shared)
    original = await Video.create(scene=shot, model_type=1, status=3, url='/media/videos/exclusive.mp4')
    await Video.create(scene=surviving_shot, model_type=1, status=3, url='/media/videos/shared.mp4')
    merged = put(root / 'videos' / 'merged' / f'chapter_{chapter.id}_merged.mp4')
    task = await AiTask.create(task_type=3, status=6, request_params={'chapter_id': chapter.id})
    exported = await ChapterExport.create(novel_id=project.id, chapter_id=chapter.id, identity_key='episode',
        source_version='v1', task=task, manifest=[{'ref': '/media/videos/shared.mp4'}], collection_complete=True)
    ref = f'/media/exports/{exported.id}/edited.mp4'
    file = put(export_media.local_path(ref))
    cover = put(export_media.local_path(f'/media/exports/{exported.id}/cover.jpg'))
    await ChapterExport.filter(id=exported.id).update(media_ref=ref)
    publication = await FinishedEpisodePublication.create(chapter=chapter, export=exported)
    draft = await ChapterEditDraft.create(chapter=chapter)

    response = await client.delete(f'/api/chapter/{chapter.id}')
    assert response.json()['code'] == 0, response.text
    assert not await Chapter.filter(id=chapter.id).exists()
    assert not await Scene.with_deleted().filter(id=shot.id).exists()
    assert not await Video.filter(id=original.id).exists()
    assert not await ChapterEditDraft.filter(id=draft.id).exists()
    assert not await ChapterExport.filter(id=exported.id).exists()
    assert not await FinishedEpisodePublication.filter(id=publication.id).exists()
    assert not await Asset.with_deleted().filter(id=owned.id).exists()
    assert await AiTask.filter(id=task.id, status=5).exists()
    await shared.refresh_from_db()
    await form.refresh_from_db()
    assert shared.source_chapters == [2] and form.chapter_numbers == [2]
    await drain_media_deletions()
    assert all(not item.exists() for item in (exclusive, merged, file, cover))
    assert shared_file.exists()


@pytest.mark.asyncio
async def test_permanent_asset_deletion_clears_bindings_but_keeps_videos(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path))
    original = put(tmp_path / 'assets' / 'original.png')
    shared_image = put(tmp_path / 'assets' / 'shared.png')
    project = await Novel.create(name='资产删除')
    chapter = await Chapter.create(novel=project, number=1, name='一', content='')
    asset = await Asset.create(novel=project, asset_type=1, canonical_name='阿岚', aliases=['小岚'],
        main_image='/media/assets/original.png')
    variant = await AssetVariant.create(asset=asset, name='雨衣', images=['/media/assets/shared.png'])
    other = await Asset.create(novel=project, asset_type=1, canonical_name='旁人', main_image='/media/assets/shared.png',
        metadata={REFERENCE_KEY: [{'asset_id': asset.id, 'variant_id': variant.id}]})
    shot = await Scene.create(chapter=chapter, sequence=1, prompt='@{小岚#雨衣}走进门，@{旁人}在窗边。',
        metadata={'asset_variant_ids': {str(asset.id): variant.id}})
    await shot.assets.add(asset, other)
    video = await Video.create(scene=shot, model_type=1, status=3, url='/media/videos/keep.mp4')
    impact = (await client.get(f'/api/asset/{asset.id}/deletion-impact')).json()
    assert impact['data'] == [{'chapter_number': 1, 'sequence': 1}]

    response = await client.delete(f'/api/asset/{asset.id}')
    assert response.json()['code'] == 0, response.text
    assert not await Asset.with_deleted().filter(id=asset.id).exists()
    assert not await AssetVariant.with_deleted().filter(id=variant.id).exists()
    await shot.refresh_from_db()
    await other.refresh_from_db()
    assert shot.prompt == '走进门，@{旁人}在窗边。'
    assert shot.metadata.get('asset_variant_ids') == {}
    assert await shot.assets.all().values_list('id', flat=True) == [other.id]
    assert other.metadata[REFERENCE_KEY] == []
    assert await Video.filter(id=video.id).exists()
    await drain_media_deletions()
    assert not original.exists()
    assert shared_image.exists()
    assert not await MediaDeletion.exists()
    recreated = await Asset.create(novel=project, asset_type=1, canonical_name='阿岚')
    assert recreated.id != asset.id


@pytest.mark.asyncio
async def test_delete_variant_updates_legacy_single_binding_and_keeps_asset(client):
    project = await Novel.create(name='形态删除')
    chapter = await Chapter.create(novel=project, number=1, name='一', content='')
    asset = await Asset.create(novel=project, asset_type=1, canonical_name='阿岚')
    form = await AssetVariant.create(asset=asset, name='雨衣', chapter_numbers=[1])
    shot = await Scene.create(chapter=chapter, sequence=1, prompt='@{阿岚#雨衣}在门口',
        metadata={'asset_variant_ids': {str(asset.id): form.id}})
    await shot.assets.add(asset)
    response = await client.delete(f'/api/asset/{asset.id}/variants/{form.id}')
    assert response.json()['code'] == 0, response.text
    await shot.refresh_from_db()
    assert shot.metadata['asset_variant_ids'][str(asset.id)] == [None]
    assert shot.prompt == '在门口'
    assert await Asset.filter(id=asset.id).exists()
    assert not await AssetVariant.with_deleted().filter(id=form.id).exists()


@pytest.mark.asyncio
async def test_accepted_video_job_has_time_to_finish_before_episode_is_deleted(client):
    project = await Novel.create(name='待结算剧集')
    chapter = await Chapter.create(novel=project, number=1, name='一', content='')
    shot = await Scene.create(chapter=chapter, sequence=1)
    video = await Video.create(scene=shot, model_type=1, external_task_id='provider-job', status=2)

    blocked = await client.delete(f'/api/chapter/{chapter.id}')
    assert blocked.json()['code'] == 409
    assert await Chapter.filter(id=chapter.id).exists()
    await Video.filter(id=video.id).update(status=3)
    deleted = await client.delete(f'/api/chapter/{chapter.id}')
    assert deleted.json()['code'] == 0
    assert not await Video.filter(id=video.id).exists()


@pytest.mark.asyncio
async def test_failed_storage_cleanup_retries_and_respects_team_and_shared_references(monkeypatch):
    from unittest.mock import AsyncMock
    from services import deleted_media

    project = await Novel.create(name='共享图片')
    generated = 'uploads/0/20261119/abcdef123456-asset-14.png'
    shared = 'uploads/8/20261119/shared.png'
    foreign = 'uploads/9/20261119/foreign.png'
    attempts = []

    async def delete_reference(ref):
        if ref == generated and ref not in attempts:
            attempts.append(ref)
            raise RuntimeError('temporary storage failure')
        attempts.append(ref)

    delete = AsyncMock(side_effect=delete_reference)
    monkeypatch.setattr(deleted_media, 'oss', type('Storage', (), {'enabled': True, 'delete': delete})())
    await Asset.create(novel=project, asset_type=1, canonical_name='保留', main_image=shared)
    await deleted_media.enqueue_media([generated, shared, foreign, '/media/../../outside.png'], 8, asset_id=14)
    await drain_media_deletions()
    assert await MediaDeletion.all().count() == 1
    await drain_media_deletions()
    assert not await MediaDeletion.exists()
    assert attempts.count(generated) == 2
    assert not {foreign, shared}.intersection(attempts)


@pytest.mark.asyncio
async def test_delete_selected_shot_video_switches_to_playable_version_and_removes_exclusive_media(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path / 'exports'))
    project = await Novel.create(name='生成视频版本')
    chapter = await Chapter.create(novel=project, number=1, name='第一集', content='')
    shot = await Scene.create(chapter=chapter, sequence=1)
    older = await Video.create(scene=shot, model_type=1, status=3, url='/media/videos/keep.mp4')
    current = await Video.create(scene=shot, model_type=1, status=3, url='/media/videos/remove.mp4')
    await Video.create(scene=shot, model_type=1, status=4)
    shot.metadata = {'workbench': {'activeVideoId': current.id, 'aspectRatio': '9:16'}}
    await shot.save(update_fields=['metadata'])
    source = await ChapterExport.create(novel_id=project.id, chapter_id=chapter.id, source_video_id=current.id,
        identity_key='shot_export', source_version='v1', manifest=[{'ref': current.url}])
    deleted_file = put(tmp_path / 'media' / 'videos' / 'remove.mp4')
    kept_file = put(tmp_path / 'media' / 'videos' / 'keep.mp4')
    poster = put(tmp_path / 'media' / 'videos' / 'posters' / 'remove-preview.webp')

    result = await client.delete(f'/api/video/{current.id}')
    assert result.json()['code'] == 0, result.text
    await shot.refresh_from_db()
    assert shot.metadata == {'current_video_id': older.id, 'workbench': {'aspectRatio': '9:16'}}
    assert not await Video.filter(id=current.id).exists()
    assert not await ChapterExport.filter(id=source.id).exists()
    await drain_media_deletions()
    assert not deleted_file.exists() and not poster.exists()
    assert kept_file.exists()


@pytest.mark.asyncio
async def test_delete_published_export_withdraws_only_its_version_and_cleans_private_files(client, tmp_path, monkeypatch):
    from models.portfolio import PortfolioEpisode, PortfolioWork

    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path / 'media'))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path / 'exports'))
    project = await Novel.create(name='已公开的成片')
    chapter = await Chapter.create(novel=project, number=1, name='第一集', content='')
    current = await ChapterExport.create(novel_id=project.id, chapter_id=chapter.id, identity_key='edit_current',
        source_version='current', recipe={'kind': 'editor_render'}, collection_complete=True)
    other = await ChapterExport.create(novel_id=project.id, chapter_id=chapter.id, identity_key='edit_older',
        source_version='old', recipe={'kind': 'editor_render'}, collection_complete=True)
    files = []
    for export in (current, other):
        ref = f'/media/exports/{export.id}/edited.mp4'
        files.append(put(export_media.local_path(ref)))
        await ChapterExport.filter(id=export.id).update(media_ref=ref)
    cover = put(export_media.local_path(f'/media/exports/{current.id}/cover.jpg'))
    work = await PortfolioWork.create(novel=project, title='作品', status='public')
    await PortfolioEpisode.create(work=work, chapter=chapter, export=current)
    await FinishedEpisodePublication.create(chapter=chapter, export=current)

    result = await client.delete(f'/api/video/exports/{current.id}')
    assert result.json()['code'] == 0, result.text
    assert (await client.get(f'/api/video/exports/{current.id}/download')).json()['code'] == 404
    assert await ChapterExport.filter(id=other.id).exists()
    assert not await PortfolioEpisode.filter(work=work).exists()
    assert not await FinishedEpisodePublication.filter(chapter=chapter).exists()
    await drain_media_deletions()
    assert not files[0].exists() and not cover.exists()
    assert files[1].exists()


@pytest.mark.asyncio
async def test_delete_enhanced_export_removes_its_mirrored_shot_version(client):
    project = await Novel.create(name='带高清版本的分镜')
    chapter = await Chapter.create(novel=project, number=1, name='第一集', content='')
    shot = await Scene.create(chapter=chapter, sequence=1)
    original = await Video.create(scene=shot, model_type=1, status=3, url='/media/videos/base.mp4')
    export = await ChapterExport.create(novel_id=project.id, chapter_id=chapter.id, source_video_id=original.id,
        identity_key='enhanced', source_version='v1', collection_complete=True)
    rendered = await Video.create(scene=shot, model_type=1, status=3, url='/media/videos/hd.mp4',
        metadata={'enhancement_export_id': export.id})
    shot.metadata = {'current_video_id': rendered.id}
    await shot.save(update_fields=['metadata'])

    result = await client.delete(f'/api/video/exports/{export.id}')
    assert result.json()['code'] == 0, result.text
    assert not await ChapterExport.filter(id=export.id).exists()
    assert not await Video.filter(id=rendered.id).exists()
    await shot.refresh_from_db()
    assert shot.metadata['current_video_id'] == original.id


@pytest.mark.asyncio
async def test_delete_chapter_composition_clears_task_and_canvas_results(client, tmp_path, monkeypatch):
    from models.agent_operation import AgentOperation
    from models.video_edit import ChapterCanvasSnapshot

    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path))
    project = await Novel.create(name='画布成片')
    chapter = await Chapter.create(novel=project, number=1, name='第一集', content='')
    ref = f'/media/videos/merged/chapter_{chapter.id}_merged_run.mp4'
    file = put(tmp_path / ref.removeprefix('/media/'))
    payload = {'chapter_id': chapter.id, 'merged_url': ref, 'video_count': 1, 'total_duration': 6}
    task = await AiTask.create(task_type=4, status=3,
        request_params={'operation': 'compose', 'novel_id': project.id, 'chapter_id': chapter.id}, response_data=payload)
    await AgentOperation.create(task=task, key='media:compose', state='completed', result=payload)
    canvas = await ChapterCanvasSnapshot.create(chapter=chapter,
        layout={'manualNodes': [{'key': 'composer', 'kind': 'video_composer', 'data': {'result': payload}}]})

    assert (await client.get(f'/api/video/merge/{chapter.id}')).json()['data']['merged_url'] == ref
    result = await client.delete(f'/api/video/merge/{chapter.id}')
    assert result.json()['code'] == 0, result.text
    await canvas.refresh_from_db()
    assert 'result' not in canvas.layout['manualNodes'][0]['data']
    assert (await client.get(f'/api/video/merge/{chapter.id}')).json()['data'] is None
    assert await Chapter.filter(id=chapter.id).exists()
    await drain_media_deletions()
    assert not file.exists()
