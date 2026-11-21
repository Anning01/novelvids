import asyncio
from datetime import timedelta

import pytest

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from services.project_overview import project_overview
from test.test_services.test_finished_episodes import finished


async def chapter_for(project, number=1):
    return await Chapter.create(novel=project, number=number, name=f"Episode {number}", content="Story")


async def video_for(scene, *, seconds=6, reported=True, status=3, url="/media/shot.mp4"):
    return await Video.create(scene=scene, model_type=1, status=status, url=url, metadata={
        "duration": 999,
        "provider_accounting": {"usage_reported": reported, "reported_seconds": seconds},
    })


@pytest.mark.asyncio
async def test_empty_overview_and_text_only_projects_have_real_zero_output():
    assert (await project_overview()).summary.project_count == 0
    project = await Novel.create(name="Text only", total_chapters=900)
    await chapter_for(project)
    overview = await project_overview()
    item = overview.items[0]
    assert item.production.chapter_count == overview.summary.chapter_count == 1
    assert item.production.completed_episode_count == 0
    assert item.production.video_seconds == 0
    assert item.production.state == "not_started"
    assert "content" not in item.model_dump()


@pytest.mark.asyncio
async def test_completed_episodes_require_successful_composition_and_preserve_completed_versions():
    project = await Novel.create(name="In production")
    chapter = await chapter_for(project)
    first = await Scene.create(chapter=chapter, sequence=1, duration=800)
    second = await Scene.create(chapter=chapter, sequence=2, duration=900)
    selected = await video_for(first, seconds=6, url="/media/current.mp4")
    await video_for(first, seconds=30, url="/media/old-version.mp4")
    await Scene.filter(id=first.id).update(metadata={"current_video_id": selected.id})
    metric = (await project_overview()).items[0].production
    assert metric.completed_episode_count == 0
    assert metric.completed_shot_count == 1 and metric.shot_count == 2
    assert metric.video_seconds == 6  # neither planned runtime nor old versions
    await video_for(second, seconds=4)
    metric = (await project_overview()).items[0].production
    assert metric.completed_episode_count == 0
    assert metric.pending_composition_count == 1
    await finished(chapter, seconds=7)
    metric = (await project_overview()).items[0].production
    assert metric.completed_episode_count == 1
    assert metric.pending_composition_count == 0
    assert metric.finished_seconds == 7
    assert metric.video_seconds == 10
    failed = await video_for(second, status=4, url=None)
    await Scene.filter(id=second.id).update(metadata={"workbench": {"activeVideoId": failed.id}})
    assert (await project_overview()).items[0].production.completed_episode_count == 1


@pytest.mark.asyncio
async def test_media_is_deduplicated_and_archived_objects_do_not_inflate_totals():
    project = await Novel.create(name="Assets")
    chapter = await chapter_for(project)
    asset = await Asset.create(novel=project, asset_type=1, canonical_name="Alex",
                               main_image="/media/a.png", angle_image_1="/media/a.png")
    await AssetVariant.create(asset=asset, name="Coat", images=["/media/a.png", "/media/b.png"])
    archived = await Asset.create(novel=project, asset_type=2, canonical_name="Old", main_image="/media/old.png")
    await AssetVariant.create(asset=archived, name="Old view", images=["/media/old-view.png"])
    await Asset.with_deleted().filter(id=archived.id).update(deleted_at=archived.updated_at)
    scene = await Scene.create(chapter=chapter, sequence=1)
    await Scene.filter(id=scene.id).update(metadata={"video_reference_media": [
        {"type": "image", "url": "/media/a.png"},  # already bound to the character
        {"type": "video", "url": "/media/reference.mp4"},
    ]})
    await video_for(scene, seconds=8)
    old_scene = await Scene.create(chapter=chapter, sequence=2)
    await video_for(old_scene, seconds=200, url="/media/archived.mp4")
    await Scene.with_deleted().filter(id=old_scene.id).update(deleted_at=old_scene.updated_at)
    voice = await AudioReference.create(nickname="voice", gender="", audio_url="/media/voice.wav",
                                        avatar_url="", asset_id="voice")
    await Novel.filter(id=project.id).update(narrator_audio_reference_id=voice.id)
    await Asset.filter(id=asset.id).update(metadata={"voice_reference_id": voice.id})
    overview = await project_overview()
    assert overview.items[0].production.asset_count == overview.summary.asset_count == 5
    assert overview.items[0].production.shot_count == 1
    assert overview.summary.video_seconds == 8


@pytest.mark.asyncio
async def test_missing_actual_duration_is_distinct_from_zero_and_scoped_totals():
    own = await Novel.create(name="Own", team_id=31)
    foreign = await Novel.create(name="Foreign", team_id=32)
    for project, reported, seconds in ((own, False, 123), (foreign, True, 50)):
        chapter = await chapter_for(project)
        scene = await Scene.create(chapter=chapter, sequence=1, duration=600)
        await video_for(scene, seconds=seconds, reported=reported)
    overview = await project_overview(31)
    assert [item.id for item in overview.items] == [own.id]
    assert overview.summary.video_seconds == 0
    assert overview.summary.unknown_duration_count == 1
    assert overview.summary.chapter_count == 1
    assert overview.items[0].production.completed_episode_count == 0
    assert overview.items[0].production.pending_composition_count == 1


@pytest.mark.asyncio
async def test_media_activity_controls_sort_and_latest_completed_episode():
    project = await Novel.create(name="Recently produced")
    latest = None
    for number in (9, 2):
        scene = await Scene.create(chapter=await chapter_for(project, number), sequence=1)
        latest = await video_for(scene, seconds=1, url=f"/media/{number}.mp4")
    other = await Novel.create(name="Created later")
    await Video.filter(id=latest.id).update(updated_at=other.updated_at + timedelta(minutes=1))
    overview = await project_overview()
    assert overview.items[0].id == project.id
    assert overview.items[0].production.latest_episode_number is None
    chapter = await Chapter.get(novel=project, number=2)
    await finished(chapter, seconds=5)
    overview = await project_overview()
    assert overview.items[0].production.latest_episode_number == 2
    assert overview.summary.finished_seconds == 5


@pytest.mark.asyncio
async def test_overview_api_is_lightweight_and_uses_the_same_summary_contract(client):
    await Novel.create(name="Visible", content="Private manuscript", tags=["科幻"], project_type="短剧")
    response = await client.get("/api/novel/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["summary"]["project_count"] == 1
    assert payload["data"]["items"][0]["tags"] == ["科幻"]
    assert "Private manuscript" not in response.text


@pytest.mark.asyncio
async def test_invalid_voice_bindings_and_foreign_uploaded_audio_are_not_counted():
    project = await Novel.create(name="Own audio", team_id=1)
    foreign = await AudioReference.create(nickname="foreign", gender="", audio_url="/media/foreign.wav",
                                          avatar_url="", asset_id="foreign", source="upload", team_id=2)
    await Asset.create(novel=project, asset_type=1, canonical_name="Foreign binding",
                       metadata={"voice_reference_id": foreign.id})
    await Asset.create(novel=project, asset_type=2, canonical_name="Invalid binding",
                       metadata={"voice_reference_id": {"invalid": True}})
    assert (await project_overview(1)).summary.asset_count == 0


@pytest.mark.parametrize("value", [None, -1, True, "unknown", float("nan"), float("inf")])
def test_only_finite_reported_video_durations_are_accepted(value):
    from services.project_overview import _reported_seconds
    assert _reported_seconds({"metadata": {"provider_accounting": {
        "usage_reported": True, "reported_seconds": value,
    }}}) is None


@pytest.mark.asyncio
async def test_overlapping_reads_share_only_the_current_scope_and_survive_disconnect(monkeypatch):
    from services import project_overview as service

    started = asyncio.Queue()
    release = asyncio.Event()
    calls = []
    original = service._load_project_overview

    async def load(team_id):
        calls.append(team_id)
        await started.put(team_id)
        await release.wait()
        return await original(team_id)

    monkeypatch.setattr(service, '_load_project_overview', load)
    first = asyncio.create_task(project_overview(7))
    assert await started.get() == 7
    same = asyncio.create_task(project_overview(7))
    other = asyncio.create_task(project_overview(8))
    global_view = asyncio.create_task(project_overview())
    assert {await started.get(), await started.get()} == {8, None}
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    await asyncio.gather(same, other, global_view)
    assert calls.count(7) == 1
    await Novel.create(name='New project', team_id=7)
    assert (await project_overview(7)).summary.project_count == 1
    assert calls.count(7) == 2


@pytest.mark.asyncio
async def test_failed_overview_can_be_retried(monkeypatch):
    from unittest.mock import AsyncMock
    from services import project_overview as service

    expected = await project_overview(7)
    load = AsyncMock(side_effect=[RuntimeError('read failed'), expected])
    monkeypatch.setattr(service, '_load_project_overview', load)
    with pytest.raises(RuntimeError, match='read failed'):
        await project_overview(7)
    assert await project_overview(7) == expected

@pytest.mark.asyncio
async def test_clip_overview_uses_current_output_for_preview_and_readiness():
    image = await Novel.create(name="Loop", author="片段创作", project_setting='{"task_type":"image","output_format":"gif","resolution":"1K"}')
    video = await Novel.create(name="Movie", author="片段创作", project_setting='{"task_type":"video"}')
    await Asset.create(novel=image, asset_type=2, canonical_name="成图", main_image="/media/loop.gif")
    await Asset.create(novel=video, asset_type=2, canonical_name="输入图", main_image="/media/input.png")
    shot = await Scene.create(chapter=await chapter_for(video), sequence=1)
    items = {i.id: i for i in (await project_overview()).items}
    assert items[image.id].clip.kind == "gif" and items[image.id].clip.resolution == "1K"
    assert items[image.id].clip.preview == "/media/loop.gif" and items[image.id].production.state == "ready"
    assert items[video.id].clip.preview is None and items[video.id].production.state != "ready"
    output = await video_for(shot)
    await Video.filter(id=output.id).update(metadata={"poster_url": "/media/poster.webp"})
    item = next(i for i in (await project_overview()).items if i.id == video.id)
    assert item.clip.kind == "video" and item.clip.preview == "/media/poster.webp"
    assert item.production.state == "ready" and item.production.completed_episode_count == 0


@pytest.mark.asyncio
async def test_legacy_clip_without_settings_still_lists_without_exposing_private_settings():
    project = await Novel.create(name="Legacy clip", author="片段创作", project_setting="unstructured legacy settings")
    await chapter_for(project)
    item = (await project_overview()).items[0]
    assert item.clip.kind is None and item.clip.preview is None
    assert "project_setting" not in item.model_dump()
