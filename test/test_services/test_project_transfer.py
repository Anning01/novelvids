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


def test_transfer_plan_leaves_cloud_body_at_its_origin_and_export_private(monkeypatch):
    from services.project_transfer.downloads import export_plan
    monkeypatch.setattr("services.project_transfer.downloads.resolve_media_url", lambda k: "https://bucket.example/"+k+"?signature=temporary")
    snapshot = {"exports":[{"id":42,"media_ref":"/media/exports/42/movie.mp4"}],
        "remake_sources":[], "assets":[{"main_image":"uploads/3/hero.png"}]}
    plan = export_plan(snapshot, 3)
    assert plan["project"]["assets"][0]["main_image"] == "novelvids:media/2.png"
    assert plan["files"][0]["url"] == "/api/video/exports/42/download" and plan["files"][0]["authenticated"]
    assert plan["files"][1]["url"].startswith("https://bucket.example/") and not plan["files"][1]["authenticated"]
    for bad in ["uploads/4/photo.png","/media/exports/900/other.mp4","/media/../private/photo.png"]:
        snapshot["assets"][0]["main_image"] = bad
        with pytest.raises(ArchiveError):
            export_plan(snapshot,3)


@pytest.mark.asyncio
async def test_import_endpoint_rejects_invalid_archive_and_imports_into_new_project(client, tmp_path, monkeypatch):
    from config import settings
    from models.novel import Novel
    from services.project_transfer.snapshot import project_snapshot
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path/"media"))
    monkeypatch.setattr(settings, "CHAPTER_EXPORT_PATH", str(tmp_path/"private"))
    novel = await Novel.create(name="归来")
    r = await client.get(f"/api/novel/{novel.id}/transfer")
    assert r.json()["data"]["project"]["novel"]["name"] == "归来" and not r.json()["data"]["files"]
    dest = tmp_path/"work.zip"
    snapshot = await project_snapshot(novel.id)
    with write_project(dest, snapshot):
        pass
    async def submit(data):
        return (await client.post("/api/novel/import-project", files={"file":("work.zip",data,"application/zip")})).json()
    assert (await submit(b"bad archive"))["code"] == 422
    restored = await submit(dest.read_bytes())
    assert restored["code"] == 0 and restored["data"]["id"] != novel.id
    snapshot["assets"]=[{"id":12,"main_image":"/some/path.png"}]
    with write_project(dest, snapshot):
        pass
    assert (await submit(dest.read_bytes()))["code"] == 422
    assert await Novel.all().count() == 2


@pytest.mark.asyncio
async def test_project_transfer_restores_browser_canvas_in_bootstrap(client,tmp_path,monkeypatch):
    from config import settings
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from services.project_transfer.snapshot import project_snapshot
    from services.project_transfer.local_media import pack_local_snapshot

    monkeypatch.setattr(settings,"MEDIA_PATH",str(tmp_path/"media"))
    monkeypatch.setattr(settings,"CHAPTER_EXPORT_PATH",str(tmp_path/"private"))
    work=await Novel.create(name="画布迁移")
    ch=await Chapter.create(novel=work,number=1,name="一",content="原文")
    actor=await Asset.create(novel=work,asset_type=1,canonical_name="演员")
    variant=await AssetVariant.create(asset=actor,name="少年")
    shot=await Scene.create(chapter=ch,sequence=1,prompt="保留提示")
    await shot.assets.add(actor)
    old=f"shot-{shot.id}"
    asset_key=f"asset-{actor.id}-variant-{variant.id}"
    view={"version":2,"viewport":{"x":4,"y":5,"zoom":0.8},"canvasSize":{"width":700,"height":500},
        "nodes":{old:{"position":{"x":10,"y":20}},asset_key:{"position":{"x":40,"y":60}}},
        "manualNodes":[{"key":"note-19","kind":"note","id":-19,"title":"笔记","data":{"content":"保留这条镜头说明"}},
                       {"key":"section-3","kind":"section","id":-3,"title":"场","data":{"node_keys":[old,asset_key,"note-19"]}}],
        "manualEdges":[{"key":"media-edge-2","source":asset_key,"target":old,"config":None}]}
    path=f"/api/novel/{work.id}/transfer"
    result=(await client.post(path,json={str(ch.id):view})).json()
    assert result["code"]==0
    assert result["data"]["project"]["canvases"][str(ch.id)]==view
    assert (await client.post(path,json={"9999":view})).json()["code"]==422
    dest=tmp_path/"canvas.zip"
    pack_local_snapshot(result["data"]["project"],dest,media_root=tmp_path/"old-media",exports_root=tmp_path/"old-exports")
    with dest.open('rb') as file:
        response=await client.post("/api/novel/import-project",files={"file":("canvas.zip",file,"application/zip")})
    copied_id=response.json()["data"]["id"]
    newch=await Chapter.get(novel_id=copied_id)
    newshot=await Scene.get(chapter=newch)
    newactor=await Asset.get(novel_id=copied_id)
    newvariant=await AssetVariant.get(asset=newactor)
    bootstrap=(await client.get("/api/workbench/bootstrap",params={"novel_id":copied_id,"chapter_id":newch.id})).json()["data"]
    saved=bootstrap["canvas_layout"]
    newkey=f"shot-{newshot.id}"
    newasset=f"asset-{newactor.id}-variant-{newvariant.id}"
    assert set(saved["nodes"])=={newkey,newasset}
    assert saved["viewport"]==view["viewport"] and saved["nodes"][newkey]==view["nodes"][old]
    assert saved["manualNodes"][0]["data"]["content"]=="保留这条镜头说明"
    assert saved["manualEdges"][0]["target"]==newkey and saved["manualEdges"][0]["source"]==newasset
    assert saved["manualNodes"][1]["data"]["node_keys"]==[newkey,newasset,"note-19"]
    assert (await project_snapshot(copied_id))["canvases"][str(newch.id)]==saved


@pytest.mark.asyncio
async def test_import_preserves_external_stable_ids_without_redirecting_an_existing_work():
    from models.novel import Novel
    from models.chapter import Chapter
    from models.scene import Scene
    from models.work_sync import WorkSyncObject
    from services.project_transfer.snapshot import project_snapshot
    from services.project_transfer.restore import restore_graph
    work=await Novel.create(name="外部创作")
    ch=await Chapter.create(novel=work,number=1,name="一",content="原稿")
    shot=await Scene.create(chapter=ch,sequence=5,prompt="镜头")
    for kind,ep,stable,local,payload in [
        ("work","","my-story",work.id,{"id":"my-story"}),
        ("episode","ep-1","ep-1",ch.id,{"manifest":{"work":{"id":"my-story"}},"scenes":[{"id":"scene-1"}]}),
        ("shot","ep-1","shot-5",shot.id,{"id":"shot-5","scene_id":"scene-1"}),
    ]:
        await WorkSyncObject.create(work_id="my-story",kind=kind,episode_id=ep,stable_id=stable,local_id=local,payload=payload)
    snapshot=await project_snapshot(work.id)
    restored=await restore_graph(snapshot,team_id=None,user_id=None)
    new_work=await WorkSyncObject.get(kind="work",local_id=restored.id)
    assert new_work.work_id!="my-story"
    assert (await WorkSyncObject.get(work_id="my-story",kind="work")).local_id==work.id
    new_episode=await WorkSyncObject.get(work_id=new_work.work_id,kind="episode")
    assert new_episode.stable_id=="ep-1" and new_episode.payload["manifest"]["work"]["id"]==new_work.stable_id
    new_shot=await WorkSyncObject.get(work_id=new_work.work_id,kind="shot",stable_id="shot-5")
    assert new_shot.local_id!=shot.id and await Scene.filter(id=new_shot.local_id,chapter_id=new_episode.local_id).exists()


def test_legacy_generated_assets_in_shared_zero_directory_remain_exportable(monkeypatch):
    from services.project_transfer.downloads import export_plan
    monkeypatch.setattr("services.project_transfer.downloads.resolve_media_url",lambda k:"https://storage.example/"+k)
    work={"exports":[],"remake_sources":[],"novel":{"cover":"uploads/0/cover.png"},
          "assets":[{"main_image":"uploads/0/actor.png","metadata":{"image_gallery":["uploads/0/actor.png"]}}],
          "videos":[{"url":"uploads/0/video.mp4","metadata":{"poster_url":"uploads/0/poster.png"}}]}
    plan=export_plan(work,7)
    assert len(plan["files"])==4
    assert plan["project"]["assets"][0]["metadata"]["image_gallery"][0]==plan["project"]["assets"][0]["main_image"]
    work["novel"]["cover"]="uploads/8/other-team.png"
    with pytest.raises(ArchiveError,match="团队"):
        export_plan(work,7)
