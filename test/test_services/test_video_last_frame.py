from pathlib import Path
from types import SimpleNamespace

import pytest

import services.video.last_frame as last_frame_module
from services.video.last_frame import LastFrameService


@pytest.mark.asyncio
async def test_本地视频通过_ffmpeg_提取尾帧并保存到媒体目录(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    source = media_root / "videos" / "3.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"video")
    monkeypatch.setattr(last_frame_module.settings, "MEDIA_PATH", str(media_root))

    class FakeLocalOSS:
        enabled = False

        def normalize_media_ref(self, raw):
            return raw

    monkeypatch.setattr(last_frame_module, "oss", FakeLocalOSS())
    seen_sources: list[Path] = []

    def fake_extract(video_path: Path, frame_path: Path):
        seen_sources.append(video_path)
        frame_path.write_bytes(b"png")

    service = LastFrameService()
    monkeypatch.setattr(service, "_extract_with_ffmpeg", fake_extract)

    result = await service.extract_and_store("/media/videos/3.mp4", 3)

    assert result == "/media/video-references/last-frame-3.png"
    assert seen_sources == [source.resolve()]
    assert (media_root / "video-references" / "last-frame-3.png").read_bytes() == b"png"


@pytest.mark.asyncio
async def test_oss视频经内网下载且提取图片经内网上传(tmp_path, monkeypatch):
    transferred_paths: list[Path] = []
    uploaded: dict[str, object] = {}

    class FakeOSS:
        enabled = True

        def normalize_media_ref(self, raw):
            return raw

        async def download_to_file(self, key, destination):
            transferred_paths.append(destination)
            assert key == "uploads/7/videos/5.mp4"
            destination.write_bytes(b"video-from-internal-oss")

        async def put_file(self, key, source, content_type):
            transferred_paths.append(source)
            uploaded.update(key=key, content_type=content_type, content=source.read_bytes())

    monkeypatch.setattr(last_frame_module, "oss", FakeOSS())
    monkeypatch.setattr(
        last_frame_module,
        "make_upload_key",
        lambda team_id, filename: f"uploads/{team_id}/{filename}",
    )
    service = LastFrameService()
    monkeypatch.setattr(
        service,
        "_extract_with_ffmpeg",
        lambda _video, frame: frame.write_bytes(b"last-frame-png"),
    )

    result = await service.extract_and_store(
        "uploads/7/videos/5.mp4",
        5,
        team_id=7,
    )

    assert result == "uploads/7/video-references/last-frame-5.png"
    assert uploaded == {
        "key": "uploads/7/video-references/last-frame-5.png",
        "content_type": "image/png",
        "content": b"last-frame-png",
    }
    assert transferred_paths
    assert all(not path.exists() for path in transferred_paths)


def test_ffmpeg只解码视频尾部并输出真实最后一帧(tmp_path, monkeypatch):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "last.png"
    captured: dict[str, list[str]] = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        output.write_bytes(b"png")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(last_frame_module.subprocess, "run", fake_run)

    LastFrameService._extract_with_ffmpeg(source, output)

    command = captured["command"]
    assert command[:5] == ["ffmpeg", "-y", "-sseof", "-1", "-i"]
    assert command[command.index("-vf") + 1] == "reverse"
    assert command[command.index("-frames:v") + 1] == "1"
