"""Complete remake import, updates, and portable project round trips."""
import json
import subprocess

import pytest
from pydantic import ValidationError

from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from schemas.work_package import Episode, ImportEpisode, ReadEpisode, UpdateShot
from services.local_mcp.sync import SyncConflict, WorkSync
from services.project_transfer.restore import restore_graph
from services.project_transfer.snapshot import project_snapshot
from test.test_services.test_local_mcp import package


@pytest.fixture
def remake_package(tmp_path):
    from prompts.creation_standards import render_asset_design
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    root = package(tmp_path / 'remake', work='remake-work')
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=10',
                    '-t', '2', '-pix_fmt', 'yuv420p', str(root / 'source.mp4')], check=True, capture_output=True)
    manifest = json.loads((root / 'episode.json').read_text())
    manifest.update(workflow_kind='remake', remake_source={'path': 'source.mp4'})
    (root / 'episode.json').write_text(json.dumps(manifest))
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    fields = json.loads(snapshot.read('asset_contract'))['zh']['person']['fields']
    prompt = render_asset_design('', {field: '具体的古代粗布视觉设定' for field in fields},
                                 'person', snapshot, 'zh', '16:9')
    (root / 'assets.json').write_text(json.dumps({'assets': [
        {'id': 'hero', 'name': '主角', 'kind': 'person', 'prompt': prompt,
         'variants': [{'id': 'winter', 'name': '冬装', 'prompt': prompt}]}
    ]}))
    board = json.loads((root / 'storyboard.json').read_text())
    board['shots'][0]['source_range'] = {'start': 0, 'end': 2}
    board['shots'][0]['visual'] = [{'asset_id': 'hero', 'variant_id': 'winter'}]
    board['shots'][0]['voices'] = [{'asset_id': 'hero', 'mode': 'os', 'text': '去哪儿', 'start': 0, 'end': 1}]
    (root / 'storyboard.json').write_text(json.dumps(board))
    return root


async def test_remake_snapshot_restore_preserves_source_and_decomposition():
    work = await Novel.create(name="重制同步验收", workflow_kind="remake")
    chapter = await Chapter.create(novel=work, number=1, name="第一集", content="", screenplay="拆解剧本")
    await RemakeSource.create(
        novel=work, chapter=chapter, episode_number=1, source_kind="upload",
        storage_provider="local", object_key="remake/sources/source.mp4", original_filename="source.mp4",
        size_bytes=12, duration_seconds=8, width=1920, height=1080,
        container_format="mp4", checksum="a" * 64, media_status="completed",
    )
    await Scene.create(chapter=chapter, sequence=1, description="拆解画面", prompt="拆解提示词",
                       duration=8, prompt_params={"shot_type": "close_up"})

    restored = await restore_graph(await project_snapshot(work.id), team_id=None, user_id=None)
    assert restored.id != work.id and restored.workflow_kind == "remake"
    copied_chapter = await Chapter.get(novel_id=restored.id)
    assert copied_chapter.screenplay == "拆解剧本"
    source = await RemakeSource.get(novel_id=restored.id)
    assert source.chapter_id == copied_chapter.id
    assert source.object_key == "remake/sources/source.mp4" and source.media_status == "completed"
    assert source.analysis_task_id is None
    shot = await Scene.get(chapter_id=copied_chapter.id)
    assert shot.prompt == "拆解提示词" and shot.duration == 8
    assert shot.prompt_params == {"shot_type": "close_up"}


@pytest.mark.parametrize('workflow,source,valid', [
    ('script', None, True), ('remake', {'path': 'source.mp4'}, True),
    ('remake', None, False), ('script', {'path': 'source.mp4'}, False),
])
def test_local_mcp_episode_source_contract(workflow, source, valid):
    data = {"format_version": 1, "work": {"id": "work", "name": "作品"},
            "episode": {"id": "ep1", "name": "第一集"}, "number": 1,
            "workflow_kind": workflow, "remake_source": source}
    if valid:
        assert Episode.model_validate(data).workflow_kind == workflow
    else:
        with pytest.raises(ValidationError):
            Episode.model_validate(data)


async def test_mcp_remake_import_read_update_retry_and_media_roundtrip(tmp_path, remake_package):
    from models.ai_task import AiTask
    from models.video import Video
    from services.project_transfer.archive import read_project
    from services.project_transfer.local_media import pack_local_snapshot
    from services.project_transfer.install import install_project
    from services.remake.materializer import RemakeMediaMaterializer
    from services.remake.progress import RemakeProgressService

    root = remake_package
    media_root = tmp_path / 'media'
    service = WorkSync(tmp_path, media_root)
    request = ImportEpisode(directory=str(root), request_id='remake-import', confirmed=True)
    receipt = await service.import_episode(request)
    assert receipt == await service.import_episode(request)
    project = await Novel.get(id=receipt['novel_id'])
    chapter = await Chapter.get(id=receipt['chapter_id'])
    assert project.workflow_kind == receipt['workflow_kind'] == 'remake'
    assert chapter.screenplay == (root / 'screenplay.md').read_text()
    source = await RemakeSource.get(novel_id=project.id)
    assert source.media_status == 'completed' and source.analysis_task_id is None
    assert source.duration_seconds == 2 and source.width == 64 and source.height == 64
    materialized = await RemakeMediaMaterializer(media_root=media_root).materialize(source, tmp_path)
    assert materialized.read_bytes() == (root / 'source.mp4').read_bytes()
    assert receipt['remake_source']['checksum'] == source.checksum
    assert (await RemakeProgressService().snapshot(project))['aggregate_status'] == 'completed'
    assert not await AiTask.all().exists()

    row = receipt['shots'][0]
    shot = await Scene.get(id=row['local_id'])
    video = await Video.create(scene=shot, model_type=1, status=3, url='/media/existing.mp4')
    before_source = await RemakeSource.filter(id=source.id).values()
    (root / 'source.mp4').unlink()
    update = UpdateShot(directory=str(root), request_id='remake-update', confirmed=True,
        work_id='remake-work', episode_id='ep1', shot_id='shot4', base_version=row['version'],
        changes={'prompt': '修订重制提示词', 'source_range': {'start': 0.5, 'end': 1.5}})
    changed = await service.update_shot(update)
    assert changed == await service.update_shot(update)
    read = await service.read_episode(ReadEpisode(work_id='remake-work', episode_id='ep1', shot_id='shot4'))
    assert read['shots'][0]['prompt'] == '修订重制提示词'
    assert read['shots'][0]['metadata']['source_range'] == {'start': 0.5, 'end': 1.5}
    assert read['shots'][0]['source_range'] == {'start': 0.5, 'end': 1.5}
    assert read['shots'][0]['metadata']['remake_source_id'] == source.id
    assert before_source == await RemakeSource.filter(id=source.id).values()
    assert (await Video.get(id=video.id)).url == '/media/existing.mp4'
    with pytest.raises(SyncConflict, match='version_conflict'):
        await service.update_shot(update.model_copy(update={'request_id': 'remake-stale'}))
    invalid = update.model_copy(update={'request_id': 'remake-range-invalid',
        'base_version': changed['shots'][0]['version'], 'changes': {'source_range': {'start': 0, 'end': 3}}})
    with pytest.raises(ValueError, match='来源时间段'):
        await service.update_shot(invalid)
    await shot.refresh_from_db()
    assert shot.prompt == '修订重制提示词'

    # The archived source and its stable mirror must survive packing after original deletion.
    (media_root / 'existing.mp4').write_bytes(b'existing render')
    archive = tmp_path / 'remake.zip'
    pack_local_snapshot(await project_snapshot(project.id), archive, media_root=media_root,
                        exports_root=media_root / 'exports')
    with archive.open('rb') as file, read_project(file, tmp_path) as unpacked:
        source_ref = unpacked.project['remake_sources'][0]['object_key']
        assert unpacked.files[source_ref].read_bytes() == materialized.read_bytes()
    with archive.open('rb') as file:
        restored = await install_project(file, media_root=media_root, exports_root=media_root / 'exports',
                                         team_id=None, user_id=None)
    copied_source = await RemakeSource.get(novel_id=restored.id)
    copied_shot = await Scene.get(chapter__novel_id=restored.id)
    assert copied_shot.metadata['remake_source_id'] == copied_source.id != source.id
    copied_media = await RemakeMediaMaterializer(media_root=media_root).materialize(copied_source, tmp_path)
    assert copied_media.read_bytes() == materialized.read_bytes()
    from models.asset import Asset
    copied_actor = await Asset.get(novel_id=restored.id)
    assert copied_actor.metadata['remake_source_ids'] == [copied_source.id]
    assert copied_shot.metadata['voice_asset_ids'] == {'hero': copied_actor.id}


@pytest.mark.parametrize('issue', ['missing', 'corrupt', 'traversal', 'no_shots', 'missing_range', 'range_overrun'])
async def test_remake_import_rejects_invalid_sources_without_partial_records(tmp_path, remake_package, issue):
    from models.work_sync import WorkSyncObject, WorkSyncRequest
    root = remake_package
    if issue == 'missing':
        (root / 'source.mp4').unlink()
    elif issue == 'corrupt':
        (root / 'source.mp4').write_bytes(b'not video')
    elif issue == 'traversal':
        manifest = json.loads((root / 'episode.json').read_text())
        manifest['remake_source']['path'] = '../source.mp4'
        (root / 'episode.json').write_text(json.dumps(manifest))
    else:
        board = json.loads((root / 'storyboard.json').read_text())
        if issue == 'no_shots':
            board['shots'] = []
        elif issue == 'missing_range':
            board['shots'][0].pop('source_range')
        else:
            board['shots'][0]['source_range']['end'] = 10
        (root / 'storyboard.json').write_text(json.dumps(board))
    before = await WorkSyncObject.all().count(), await WorkSyncRequest.all().count()
    with pytest.raises((ValueError, OSError)):
        await WorkSync(tmp_path, tmp_path / 'media').import_episode(
            ImportEpisode(directory=str(root), request_id='bad-remake', confirmed=True))
    assert not await Novel.all().exists() and not await RemakeSource.all().exists()
    assert before == (await WorkSyncObject.all().count(), await WorkSyncRequest.all().count())


async def test_remake_multiepisode_rejects_mixed_workflows(tmp_path, remake_package):
    service = WorkSync(tmp_path, tmp_path / 'media')
    root = remake_package
    first = await service.import_episode(ImportEpisode(directory=str(root), request_id='first-remake', confirmed=True))
    manifest = json.loads((root / 'episode.json').read_text())
    manifest.update(episode={'id': 'ep2', 'name': '第二集'}, number=2)
    (root / 'episode.json').write_text(json.dumps(manifest))
    second = await service.import_episode(ImportEpisode(directory=str(root), request_id='second-remake', confirmed=True))
    assert first['novel_id'] == second['novel_id']
    assert await RemakeSource.filter(novel_id=first['novel_id']).count() == 2
    manifest.update(workflow_kind='script', remake_source=None, episode={'id': 'ep3', 'name': '第三集'}, number=3)
    (root / 'episode.json').write_text(json.dumps(manifest))
    board = json.loads((root / 'storyboard.json').read_text())
    board['shots'][0].pop('source_range')
    (root / 'storyboard.json').write_text(json.dumps(board))
    with pytest.raises(SyncConflict, match='workflow_kind_conflict'):
        await service.import_episode(ImportEpisode(directory=str(root), request_id='mixed-remake', confirmed=True))
    assert await Chapter.filter(novel_id=first['novel_id']).count() == 2


async def test_remake_import_rolls_back_after_source_persistence(tmp_path, remake_package, monkeypatch):
    from models.asset import Asset
    from models.work_sync import WorkSyncObject, WorkSyncRequest
    service = WorkSync(tmp_path, tmp_path / 'media')

    async def fail(*args, **kwargs):
        assert await RemakeSource.all().exists()
        raise RuntimeError('injected write failure')

    monkeypatch.setattr(service, 'persist_shot', fail)
    with pytest.raises(RuntimeError, match='injected write failure'):
        await service.import_episode(ImportEpisode(directory=str(remake_package), request_id='rollback', confirmed=True))
    for model in (Novel, Chapter, Asset, Scene, RemakeSource, WorkSyncObject, WorkSyncRequest):
        assert not await model.all().exists()
    assert not (remake_package / 'sync-receipt.json').exists()


async def test_concurrent_remake_imports_are_idempotent(tmp_path, remake_package):
    import asyncio
    service = WorkSync(tmp_path, tmp_path / 'media')
    request = ImportEpisode(directory=str(remake_package), request_id='concurrent-remake', confirmed=True)
    one, two = await asyncio.gather(service.import_episode(request), service.import_episode(request))
    assert one == two
    assert await Novel.all().count() == await Chapter.all().count() == await RemakeSource.all().count() == 1


async def test_script_import_rejects_remake_ranges(tmp_path):
    root = package(tmp_path / 'script')
    board = json.loads((root / 'storyboard.json').read_text())
    board['shots'][0]['source_range'] = {'start': 0, 'end': 1}
    (root / 'storyboard.json').write_text(json.dumps(board))
    with pytest.raises(ValueError, match='普通剧本'):
        await WorkSync(tmp_path, tmp_path / 'media').import_episode(
            ImportEpisode(directory=str(root), request_id='script-range', confirmed=True))
    assert not await Novel.all().exists()
