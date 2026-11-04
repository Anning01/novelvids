import asyncio
import subprocess
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from controllers.video import video_controller
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.usage_record import ModelUsageRecord
from models.video import Video
from services.video.last_frame import LastFrameExtractionError


async def setup_video(*, status=3, url="/media/existing.mp4", metadata=None):
    novel = await Novel.create(name="Recover an existing tail", team_id=7)
    chapter = await Chapter.create(novel=novel, number=1, name="One", content="Story")
    scene = await Scene.create(chapter=chapter, sequence=1)
    following = await Scene.create(chapter=chapter, sequence=2, prompt="Keep this shot")
    video = await Video.create(scene=scene, status=status, url=url, model_type=1,
                               metadata={"return_last_frame": False, **(metadata or {})})
    return video, following


@pytest.mark.asyncio
async def test_forgotten_tail_is_extracted_once_and_linked_without_generation_or_billing(monkeypatch):
    video, following = await setup_video()
    extract = AsyncMock(return_value="uploads/7/tail.png")
    provider = AsyncMock()
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", extract)
    monkeypatch.setattr("controllers.video.get_generator", provider)
    results = await asyncio.gather(*(video_controller.extract_last_frame(video.id) for _ in range(2)))
    extract.assert_awaited_once_with(video.url, video.id, team_id=7)
    provider.assert_not_called()
    assert results[-1].metadata["last_frame_url"] == "uploads/7/tail.png"
    assert results[-1].metadata["last_frame_source"] == "ffmpeg"
    assert results[-1].metadata["return_last_frame"] is False
    assert results[-1].metadata["last_frame_injected_scene_id"] == following.id
    await following.refresh_from_db()
    assert "Keep this shot" in following.prompt
    assert len(following.metadata["video_reference_media"]) == 1
    assert await Video.all().count() == 1
    assert await ModelUsageRecord.all().count() == 0


@pytest.mark.asyncio
async def test_input_keyframe_is_not_mistaken_for_the_generated_tail(monkeypatch):
    video, _ = await setup_video(metadata={"last_frame_url": "/media/input-keyframe.png"})
    extract = AsyncMock(return_value="/media/actual-tail.png")
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", extract)
    result = await video_controller.extract_last_frame(video.id)
    extract.assert_awaited_once()
    assert result.metadata["last_frame_url"] == "/media/actual-tail.png"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,url", [(2, "/media/pending.mp4"), (4, "/media/failed.mp4"), (3, None)])
async def test_unavailable_video_is_rejected_without_extracting(monkeypatch, status, url):
    video, following = await setup_video(status=status, url=url)
    extract = AsyncMock()
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", extract)
    with pytest.raises(HTTPException) as error:
        await video_controller.extract_last_frame(video.id)
    assert error.value.status_code == 400
    extract.assert_not_awaited()
    await following.refresh_from_db()
    assert following.prompt == "Keep this shot"


@pytest.mark.asyncio
async def test_extraction_failure_preserves_video_and_next_shot_and_can_be_retried(monkeypatch):
    video, following = await setup_video()
    extract = AsyncMock(side_effect=LastFrameExtractionError("missing source"))
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", extract)
    with pytest.raises(HTTPException) as error:
        await video_controller.extract_last_frame(video.id)
    assert error.value.status_code == 503
    await video.refresh_from_db()
    await following.refresh_from_db()
    assert video.status == 3 and video.url == "/media/existing.mp4"
    assert "last_frame_source" not in video.metadata
    assert following.prompt == "Keep this shot"
    extract.side_effect = None
    extract.return_value = "/media/recovered-tail.png"
    assert (await video_controller.extract_last_frame(video.id)).metadata["last_frame_source"] == "ffmpeg"


@pytest.mark.asyncio
async def test_api_exposes_a_real_recovered_tail_using_existing_video_response(client, monkeypatch, tmp_path):
    from config import settings
    from types import SimpleNamespace

    video, following = await setup_video()
    source = tmp_path / "existing.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=32x32:r=10:d=0.5", str(source)],
                   check=True, capture_output=True, timeout=30)
    monkeypatch.setattr(settings, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr("services.video.last_frame.oss", SimpleNamespace(enabled=False, normalize_media_ref=lambda value: value))
    response = await client.post(f"/api/video/{video.id}/last-frame")
    assert response.json()["code"] == 0, response.text
    frame = f"/media/video-references/last-frame-{video.id}.png"
    assert response.json()["data"]["metadata"]["last_frame_url"] == frame
    assert (tmp_path / frame.removeprefix("/media/")).read_bytes().startswith(b"\x89PNG")
    await following.refresh_from_db()
    assert following.metadata["video_reference_media"][0]["url"] == frame
    await video.refresh_from_db()
    assert video.status == 3 and video.url == "/media/existing.mp4"


@pytest.mark.asyncio
async def test_failed_persistence_rolls_back_next_shot_reference(monkeypatch):
    video, following = await setup_video()
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", AsyncMock(return_value="/media/tail.png"))
    monkeypatch.setattr(Video, "save", AsyncMock(side_effect=RuntimeError("database write failed")))
    with pytest.raises(RuntimeError, match="database write failed"):
        await video_controller.extract_last_frame(video.id)
    await following.refresh_from_db()
    assert following.prompt == "Keep this shot"
    assert not (following.metadata or {}).get("video_reference_media")


@pytest.mark.asyncio
async def test_extracting_the_final_shot_still_returns_a_downloadable_frame(monkeypatch):
    video, following = await setup_video()
    await Video.filter(id=video.id).update(scene_id=following.id)
    monkeypatch.setattr("controllers.video.last_frame_service.extract_and_store", AsyncMock(return_value="/media/tail.png"))
    result = await video_controller.extract_last_frame(video.id)
    assert result.metadata["last_frame_url"] == "/media/tail.png"
    assert result.metadata["last_frame_injected_scene_id"] is None
