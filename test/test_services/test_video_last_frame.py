from pathlib import Path
import errno
import os
import subprocess
from types import SimpleNamespace

import pytest

import services.video.last_frame as last_frame_module
from services.video.last_frame import LastFrameService


@pytest.mark.asyncio
async def test_local_tail_is_published_atomically_when_system_temp_is_on_another_filesystem(tmp_path, monkeypatch):
    media_root = tmp_path / 'media'
    media_root.mkdir()
    source = media_root / 'video.mp4'
    source.write_bytes(b'video')
    monkeypatch.setattr(last_frame_module.settings, 'MEDIA_PATH', str(media_root))
    monkeypatch.setattr(last_frame_module, 'oss', SimpleNamespace(enabled=False, normalize_media_ref=lambda value: value))
    service = LastFrameService()
    monkeypatch.setattr(service, '_extract_with_ffmpeg', lambda _video, frame: frame.write_bytes(b'complete-png'))
    real_replace = os.replace
    publications = []

    def reject_cross_device_replace(source_path, destination):
        publications.append((Path(source_path), Path(destination)))
        if not Path(source_path).is_relative_to(media_root):
            raise OSError(errno.EXDEV, 'Invalid cross-device link')
        real_replace(source_path, destination)

    monkeypatch.setattr(last_frame_module.os, 'replace', reject_cross_device_replace)
    result = await service.extract_and_store('/media/video.mp4', 37)
    destination = media_root / 'video-references/last-frame-37.png'
    assert result == '/media/video-references/last-frame-37.png'
    assert destination.read_bytes() == b'complete-png'
    assert len(publications) == 1 and publications[0][0].parent.parent == destination.parent
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.asyncio
async def test_staging_failure_keeps_existing_tail_and_removes_temporary_files(tmp_path, monkeypatch):
    media_root = tmp_path / 'media'
    destination = media_root / 'video-references/last-frame-37.png'
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b'previous-png')
    (media_root / 'video.mp4').write_bytes(b'video')
    monkeypatch.setattr(last_frame_module.settings, 'MEDIA_PATH', str(media_root))
    monkeypatch.setattr(last_frame_module, 'oss', SimpleNamespace(enabled=False, normalize_media_ref=lambda value: value))
    service = LastFrameService()
    monkeypatch.setattr(service, '_extract_with_ffmpeg', lambda _video, frame: frame.write_bytes(b'new-png'))

    def fail_copy(*_args):
        raise OSError(errno.ENOSPC, 'No space left on device')

    monkeypatch.setattr('shutil.copyfile', fail_copy)
    with pytest.raises(OSError):
        await service.extract_and_store('/media/video.mp4', 37)
    assert destination.read_bytes() == b'previous-png'
    assert list(destination.parent.iterdir()) == [destination]


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


@pytest.mark.asyncio
async def test_real_ffmpeg_extracts_the_blue_ending_not_the_red_opening(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    source = media_root / "videos" / "real-tail.mp4"
    source.parent.mkdir(parents=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=32x32:r=10:d=1",
        "-f", "lavfi", "-i", "color=blue:s=32x32:r=10:d=1", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
        "-pix_fmt", "yuv420p", str(source),
    ], check=True, capture_output=True, timeout=30)
    monkeypatch.setattr(last_frame_module.settings, "MEDIA_PATH", str(media_root))
    monkeypatch.setattr(last_frame_module, "oss", SimpleNamespace(enabled=False, normalize_media_ref=lambda value: value))
    result = await LastFrameService().extract_and_store("/media/videos/real-tail.mp4", 37)
    image = media_root / result.removeprefix("/media/")
    rgb = subprocess.run(["ffmpeg", "-v", "error", "-i", str(image), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         check=True, capture_output=True, timeout=30).stdout
    assert len(rgb) == 32 * 32 * 3
    assert rgb[0] < 20 and rgb[2] > 230
