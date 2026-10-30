from types import SimpleNamespace
from pathlib import Path

import pytest
import services.video.merge as merge_module
from services.video.merge import VideoMerger


def test_单个分镜也会产出统一的章节完整视频(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"single-video")
    merger = VideoMerger()
    merger.output_dir = str(tmp_path / "merged")
    merger._get_video_path = lambda _video: str(source)

    url = merger.merge_videos([SimpleNamespace(id=8, url="/media/videos/8.mp4")], 337)

    output = tmp_path / "merged" / "chapter_337_merged.mp4"
    assert url == "/media/videos/merged/chapter_337_merged.mp4"
    assert output.read_bytes() == b"single-video"


def test_有声与无声分镜可以生成混合音轨合并命令(tmp_path, monkeypatch):
    sources = [tmp_path / "with-audio.mp4", tmp_path / "no-audio.mp4"]
    for source in sources:
        source.write_bytes(b"video")
    merger = VideoMerger()
    merger.output_dir = str(tmp_path / "merged")
    merger._get_video_path = lambda video: str(sources[video.id - 1])
    audio_states = iter([True, False])
    monkeypatch.setattr(merge_module, "_check_audio_stream", lambda _path: next(audio_states))
    monkeypatch.setattr(merge_module, "_probe_duration", lambda _path: 1.25)
    monkeypatch.setattr(merge_module, "_video_dimensions", lambda _path: (864, 496))
    captured: dict[str, list[str]] = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        output = command[-1]
        with open(output, "wb") as target:
            target.write(b"merged")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(merge_module.subprocess, "run", fake_run)

    merger.merge_videos(
        [SimpleNamespace(id=1, url=""), SimpleNamespace(id=2, url="")],
        337,
    )

    filter_complex = captured["command"][captured["command"].index("-filter_complex") + 1]
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]" in filter_complex
    assert "atrim=duration=1.25" in filter_complex


@pytest.mark.asyncio
async def test_oss视频经内网物化后合并并上传且清理临时文件(monkeypatch):
    transferred_paths: list[Path] = []
    uploaded: dict[str, object] = {}

    class FakeOSS:
        enabled = True

        def normalize_media_ref(self, raw):
            return raw

        def resolve_url(self, raw):
            return f"https://cdn.example.com/{raw}"

        async def download_to_file(self, key, destination):
            transferred_paths.append(destination)
            destination.write_bytes(f"video:{key}".encode())

        async def put_file(self, key, source, content_type):
            transferred_paths.append(source)
            uploaded.update(
                key=key,
                content_type=content_type,
                content=source.read_bytes(),
            )

    monkeypatch.setattr(merge_module, "oss", FakeOSS())
    merger = VideoMerger()

    url = await merger.merge_videos_from_storage(
        [SimpleNamespace(id=3, url="uploads/7/20260822/video-3.mp4")],
        chapter_id=337,
        team_id=7,
    )

    assert url == (
        "https://cdn.example.com/"
        "uploads/7/videos/merged/chapter_337_merged.mp4"
    )
    assert uploaded == {
        "key": "uploads/7/videos/merged/chapter_337_merged.mp4",
        "content_type": "video/mp4",
        "content": b"video:uploads/7/20260822/video-3.mp4",
    }
    assert transferred_paths
    assert all(not path.exists() for path in transferred_paths)


@pytest.mark.parametrize('audio', ['both', 'mixed', 'none'])
def test_mixed_resolution_clips_merge_at_hd_without_stretching_or_losing_audio(tmp_path, audio):
    import subprocess
    from services.video_enhancement.media import inspect_media, file_digest
    from test.test_services.test_video_enhancement_media import fixture_video

    paths = [tmp_path / '480p.mp4', tmp_path / '1080p.mp4']
    fixture_video(paths[0], size='864x496')
    fixture_video(paths[1], size='1920x1080')
    for index in ([1] if audio == 'mixed' else [0, 1] if audio == 'none' else []):
        silent = tmp_path / f'silent-{index}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(paths[index]),
                        '-an', '-c:v', 'copy', str(silent)], check=True, capture_output=True)
        paths[index] = silent
    original_hashes = [file_digest(path) for path in paths]
    output = tmp_path / 'merged.mp4'
    VideoMerger().merge_paths([str(path) for path in paths], str(output))
    probe = inspect_media(output)
    assert (probe.width, probe.height) == (1920, 1080)
    assert abs(float(probe.duration) - 1) < .15
    assert bool(probe.audio_streams) == (audio != 'none')
    assert [file_digest(path) for path in paths] == original_hashes
