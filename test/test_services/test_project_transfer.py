import hashlib
from io import BytesIO
import json
from zipfile import ZipFile

import pytest

from services.project_transfer.archive import ArchiveError, read_project, write_project


def test_streamed_archive_round_trip_and_cleanup(tmp_path):
    content = b"scene footage" * 150_000
    manifest = {"novel": {"name": "救人"}, "videos": []}
    output = tmp_path / "救人.zip"
    with write_project(output, manifest) as writer:
        ref = writer.add_media(BytesIO(content), ".mp4")
        manifest["videos"].append({"url": ref})
    with output.open("rb") as file, read_project(file, tmp_path) as project:
        assert project.project == manifest
        path = project.files[ref]
        assert path.read_bytes() == content
    assert not path.exists()
    # A retry that fails cannot replace the only complete export.
    previous = output.read_bytes()
    with pytest.raises(ArchiveError), write_project(output, manifest) as writer:
        writer.add_media(BytesIO(content), ".html")
    assert output.read_bytes() == previous


@pytest.mark.parametrize("change", ["traversal", "duplicate", "digest", "size", "unlisted", "version"])
def test_invalid_archives_do_not_expose_partially_imported_media(tmp_path, change):
    blob = BytesIO()
    item = {"member": "media/1.png", "byte_length": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    manifest = {"format": "novelvids.project", "version": 1, "project": {}, "media": [item]}
    if change == "traversal":
        item["member"] = "../outside.png"
    if change == "size":
        item["byte_length"] = 900
    if change == "digest":
        item["sha256"] = "0" * 64
    if change == "duplicate":
        manifest["media"].append(item.copy())
    if change == "version":
        manifest["version"] = 50
    with ZipFile(blob, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
        archive.writestr(item["member"], b"abc")
        if change == "unlisted":
            archive.writestr("extra", b"unused")
    with pytest.raises(ArchiveError), read_project(blob, tmp_path):
        pytest.fail("partial project exposed")
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_snapshot_preserves_the_script_and_bound_assets_without_accounts(tmp_path):
    from models.novel import Novel
    from models.chapter import Chapter
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.scene import Scene
    from models.video import Video
    from services.project_transfer.snapshot import project_snapshot

    work = await Novel.create(name="救人", created_by=9000, storyboard_enabled=True)
    episode = await Chapter.create(novel=work, number=1, name="救人", content="原文", screenplay="导演稿")
    actor = await Asset.create(novel=work, asset_type=1, canonical_name="徐长寿")
    form = await AssetVariant.create(asset=actor, name="放牛娃", images=["/media/boy.png"])
    scene = await Scene.create(chapter=episode, sequence=5, prompt="通用稿",
        metadata={"asset_variant_ids": {str(actor.id): form.id}, "api_metadata":{"api_key":"must not be exported"}})
    await scene.assets.add(actor)
    await Video.create(scene=scene, model_type=1, status=3, url="/media/shot.mp4")
    another = await Novel.create(name="其他作品")
    await Chapter.create(novel=another, number=1, name="无关", content="私密文本")
    snapshot = await project_snapshot(work.id)
    assert "created_by" not in snapshot["novel"] and snapshot["novel"]["storyboard_enabled"]
    assert len(snapshot["chapters"]) == 1 and snapshot["chapters"][0]["screenplay"] == "导演稿"
    assert snapshot["scenes"][0]["asset_ids"] == [actor.id]
    assert snapshot["scenes"][0]["metadata"] == {"asset_variant_ids": {str(actor.id): form.id}}
    assert snapshot["videos"][0]["url"] == "/media/shot.mp4"
    assert snapshot["variants"][0]["images"] == ["/media/boy.png"]


def test_local_media_and_prompt_mentions_use_the_same_offline_file(tmp_path):
    from services.project_transfer.local_media import pack_local_snapshot, translate
    from urllib.parse import quote

    media = tmp_path / 'media'
    media.mkdir()
    (media / '少年.png').write_bytes(b'character image')
    exports = tmp_path / 'finished'
    exports.mkdir()
    (exports / 'episode.mp4').write_bytes(b'video')
    original = '/media/少年.png'
    prompt = '@{参考图片:' + quote(original, safe='') + '} 抬起头，站在门边。'
    dest = tmp_path / 'offline.zip'
    pack_local_snapshot({'prompt':prompt, 'main_image':original, 'media_ref':'/media/exports/episode.mp4'},
                        dest, media_root=media, exports_root=exports)
    with dest.open('rb') as file, read_project(file, tmp_path) as data:
        assert len(data.files) == 2
        assert data.files[data.project['main_image']].read_bytes() == b'character image'
        assert data.files[data.project['media_ref']].read_bytes() == b'video'
        refs = {data.project['main_image']: original, data.project['media_ref']: '/media/new.mp4'}
        restored = translate(data.project, lambda value: refs.get(value, value))
        assert restored['prompt'] == prompt
    previous = dest.read_bytes()
    for value in ('/media/../finished/episode.mp4', '/media/missing.png', 'https://example.invalid/private.png'):
        with pytest.raises(ArchiveError):
            pack_local_snapshot({'main_image': value}, dest, media_root=media, exports_root=exports)
        assert dest.read_bytes() == previous


@pytest.mark.asyncio
async def test_restore_assigns_new_ids_and_rolls_back_a_dangling_link():
    from copy import deepcopy
    from models.novel import Novel
    from models.chapter import Chapter
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.scene import Scene
    from models.video import Video
    from services.project_transfer.snapshot import project_snapshot
    from services.project_transfer.restore import restore_graph

    work = await Novel.create(name="救人")
    episode = await Chapter.create(novel=work, number=1, name="救人", content="原文", screenplay="导演稿")
    hero = await Asset.create(novel=work, canonical_name="徐长寿", asset_type=1)
    form = await AssetVariant.create(asset=hero, name="放牛娃")
    shot = await Scene.create(chapter=episode, sequence=5, prompt="接窝头", metadata={"asset_variant_ids":{str(hero.id): form.id}})
    await shot.assets.add(hero)
    vid = await Video.create(scene=shot, status=3, model_type=1, url="/media/current.mp4")
    await Scene.filter(id=shot.id).update(metadata={**shot.metadata, "current_video_id": vid.id})
    snapshot = await project_snapshot(work.id)
    copy = await restore_graph(snapshot, team_id=None, user_id=125)
    assert copy.name != work.name and copy.created_by == 125
    cloned = await project_snapshot(copy.id)
    actor, = cloned["assets"]
    variant, = cloned["variants"]
    new, = cloned["scenes"]
    video, = cloned["videos"]
    assert actor["id"] != hero.id and variant["asset_id"] == actor["id"]
    assert video["scene_id"] == new["id"] and new["metadata"]["current_video_id"] == video["id"]
    assert new["asset_ids"] == [actor["id"]]
    assert new["metadata"]["asset_variant_ids"] == {str(actor["id"]): variant["id"]}
    assert cloned["chapters"][0]["screenplay"] == "导演稿"
    corrupt = deepcopy(snapshot)
    corrupt["scenes"][0]["asset_ids"] = [100000]
    with pytest.raises(ArchiveError):
        await restore_graph(corrupt, team_id=None, user_id=125)
    assert await Novel.all().count() == 2


@pytest.mark.asyncio
async def test_zip_restores_offline_media_and_prompt_bindings_into_new_project(tmp_path):
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from services.project_transfer.snapshot import project_snapshot
    from services.project_transfer.local_media import pack_local_snapshot
    from services.project_transfer.install import install_project
    from urllib.parse import quote

    original_media = tmp_path / "origin"
    original_media.mkdir()
    original = original_media / "board.png"
    original.write_bytes(b"storyboard image bytes")
    project = await Novel.create(name="原始作品")
    chapter = await Chapter.create(novel=project, number=1, name="第一集", content="原文")
    await Scene.create(chapter=chapter, sequence=4, prompt="@{参考图片:%2Fmedia%2Fboard.png}",
        metadata={"storyboard_sheet":{"image_url":"/media/board.png"}})
    snapshot = await project_snapshot(project.id)
    archive = tmp_path / "作品.zip"
    pack_local_snapshot(snapshot, archive, media_root=original_media, exports_root=tmp_path/"private")
    original.unlink()
    with archive.open("rb") as file:
        result = await install_project(file, media_root=tmp_path/"local", exports_root=tmp_path/"exports", team_id=None, user_id=None)
    scene = await Scene.get(chapter__novel_id=result.id)
    ref = scene.metadata["storyboard_sheet"]["image_url"]
    assert ref.startswith("/media/project-imports/")
    assert (tmp_path/"local"/ref.removeprefix("/media/")).read_bytes() == b"storyboard image bytes"
    assert scene.prompt == "@{参考图片:" + quote(ref,safe="") + "}"


@pytest.mark.asyncio
async def test_completed_episode_is_playable_after_import_and_keeps_private_storage(tmp_path):
    from models.novel import Novel
    from models.chapter import Chapter
    from models.ai_task import AiTask
    from models.chapter_export import ChapterExport
    from models.finished_episode import FinishedEpisodePublication
    from services.finished_episodes import completed_edit_rows
    from services.project_transfer.snapshot import project_snapshot
    from services.project_transfer.local_media import pack_local_snapshot
    from services.project_transfer.install import install_project

    novel = await Novel.create(name="完成的片子")
    chapter = await Chapter.create(novel=novel, number=1, name="第一集", content="原文")
    old_task = await AiTask.create(task_type=4, status=3, request_params={"api_key": "not portable"})
    source = await ChapterExport.create(novel_id=novel.id, chapter_id=chapter.id, task=old_task,
        identity_key="first-export", source_version="first", collection_complete=True, recipe={"kind":"editor_render","revision":1},
        media_ref="/media/exports/movie.mp4")
    await FinishedEpisodePublication.create(chapter=chapter, export=source)
    private = tmp_path/"old-private"
    private.mkdir()
    (private/"movie.mp4").write_bytes(b"finished episode")
    bundle = tmp_path/"finished.zip"
    pack_local_snapshot(await project_snapshot(novel.id),bundle,media_root=tmp_path/"old-media",exports_root=private)
    with bundle.open("rb") as file:
        imported = await install_project(file, media_root=tmp_path/"media",exports_root=tmp_path/"new-private",team_id=None,user_id=None)
    episode = await Chapter.get(novel=imported)
    finished, = await completed_edit_rows([episode.id])
    version = await ChapterExport.get(id=finished["id"]).select_related("task")
    assert version.id != source.id and version.task_id != old_task.id and version.task.stage == "project_import"
    assert version.media_ref.startswith("/media/exports/imports/")
    assert (tmp_path/"new-private"/version.media_ref.removeprefix("/media/exports/")).read_bytes() == b"finished episode"
    assert not (tmp_path/"media").exists()
