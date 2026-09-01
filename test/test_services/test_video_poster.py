from pathlib import Path

import cv2
import numpy as np
import pytest

import services.video.poster as poster_module
from services.video.poster import VideoPosterService, video_poster_reference


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
