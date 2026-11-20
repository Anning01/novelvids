from pathlib import Path

import cv2
import numpy as np
import pytest

import services.video.poster as poster_module
from services.video.poster import VideoPosterService, video_media_url, video_poster_reference


def _write_frame(path: Path) -> None:
    success, encoded = cv2.imencode(
        ".png",
        np.full((720, 1280, 3), (30, 80, 160), dtype=np.uint8),
    )
    assert success
    path.write_bytes(encoded.tobytes())


def test_video_poster_reference_is_deterministic():
    assert video_poster_reference(
        "/media/videos/7.mp4",
        "thumbnail",
    ) == "/media/videos/posters/7-thumbnail.webp"
    assert video_poster_reference(
        "uploads/2/videos/7.mp4",
        "preview",
    ) == "uploads/2/videos/posters/7-preview.webp"
    assert video_poster_reference(
        "media/videos/7.mp4",
        "thumbnail",
    ) == "/media/videos/posters/7-thumbnail.webp"
    assert video_poster_reference("https://external.example/7.mp4", "preview") is None


def test_reused_local_media_paths_get_new_urls_in_history_and_polling(tmp_path, monkeypatch):
    from schemas.video import VideoOut, VideoQueryOut
    from datetime import datetime, timezone

    monkeypatch.setattr(poster_module.settings, "MEDIA_PATH", str(tmp_path))
    source = tmp_path / "videos/7.mp4"
    poster = tmp_path / "videos/posters/7-preview.webp"
    poster.parent.mkdir(parents=True)
    source.write_bytes(b"old video")
    poster.write_bytes(b"old poster")
    video_url = "/media/videos/7.mp4"
    poster_url = "/media/videos/posters/7-preview.webp"
    data = {"id": 7, "scene_id": 1, "status": 3, "url": video_url,
            "metadata": {"poster_url": poster_url}}
    old = VideoQueryOut.model_validate(data)
    source.write_bytes(b"new video version")
    poster.write_bytes(b"new poster version")
    now = datetime.now(timezone.utc)
    new = VideoOut.model_validate({**data, "created_at": now, "updated_at": now})
    assert old.url.startswith(video_url + "?media_v=") and new.url != old.url
    assert old.metadata["poster_url"].startswith(poster_url + "?media_v=")
    assert new.metadata["poster_url"] != old.metadata["poster_url"]
    assert video_media_url(new.url) == new.url
    assert video_media_url("https://media.example/7.mp4?signature=valid") == "https://media.example/7.mp4?signature=valid"


@pytest.mark.asyncio
async def test_local_video_generates_two_webp_posters(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    source = media_root / "videos/7.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    monkeypatch.setattr(poster_module.settings, "MEDIA_PATH", str(media_root))

    class FakeLocalOSS:
        enabled = False

        def normalize_media_ref(self, raw):
            return raw

    monkeypatch.setattr(poster_module, "oss", FakeLocalOSS())
    service = VideoPosterService()
    monkeypatch.setattr(service, "_extract_with_ffmpeg", lambda _video, frame: _write_frame(frame))

    result = await service.extract_and_store("/media/videos/7.mp4", 7)

    assert result == {
        "poster_thumbnail_url": "/media/videos/posters/7-thumbnail.webp",
        "poster_url": "/media/videos/posters/7-preview.webp",
    }
    thumbnail = media_root / "videos/posters/7-thumbnail.webp"
    preview = media_root / "videos/posters/7-preview.webp"
    assert thumbnail.is_file()
    assert preview.is_file()
    decoded = cv2.imdecode(np.frombuffer(thumbnail.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (180, 320)


def test_ffmpeg_poster_seeks_before_decoding(tmp_path, monkeypatch):
    source = tmp_path / "video.mp4"
    output = tmp_path / "poster.png"
    source.write_bytes(b"video")
    captured: dict[str, list[str]] = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        _write_frame(output)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(poster_module.subprocess, "run", fake_run)
    VideoPosterService._extract_with_ffmpeg(source, output)

    command = captured["command"]
    assert command[command.index("-ss") + 1] == "0.1"
    assert command[command.index("-frames:v") + 1] == "1"
