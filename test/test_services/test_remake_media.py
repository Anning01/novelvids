from pathlib import Path

import pytest

from exceptions.remake import RemakeError
from services.remake.media import MAX_REMAKE_BYTES, RemakeMediaValidator


def valid_probe(duration: str = "1200") -> dict:
    return {
        "format": {
            "duration": duration,
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        },
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }


def test_media_contract_accepts_exact_size_and_duration_boundaries():
    result = RemakeMediaValidator.validate_probe(
        original_filename="边界.MP4",
        size_bytes=MAX_REMAKE_BYTES,
        probe=valid_probe(),
        checksum="a" * 64,
        mime_type="video/mp4",
    )

    assert result.size_bytes == MAX_REMAKE_BYTES
    assert result.duration_seconds == 1200
    assert result.container_format == "mp4"
    assert result.width == 1920
    assert result.height == 1080


@pytest.mark.parametrize(
    ("filename", "size_bytes", "probe", "error_code"),
    [
        ("demo.avi", 10, valid_probe(), "REMAKE_MEDIA_EXTENSION_UNSUPPORTED"),
        ("demo.mp4", MAX_REMAKE_BYTES + 1, valid_probe(), "REMAKE_MEDIA_SIZE_EXCEEDED"),
        ("demo.mp4", 10, valid_probe("1200.001"), "REMAKE_MEDIA_DURATION_EXCEEDED"),
        (
            "demo.mp4",
            10,
            {"format": {"duration": "10", "format_name": "matroska"}, "streams": []},
            "REMAKE_MEDIA_INVALID_CONTAINER",
        ),
        (
            "demo.mov",
            10,
            {"format": {"duration": "10", "format_name": "mov,mp4"}, "streams": [{"codec_type": "audio"}]},
            "REMAKE_MEDIA_VIDEO_STREAM_MISSING",
        ),
        ("demo.mov", 10, valid_probe("0"), "REMAKE_MEDIA_DURATION_INVALID"),
    ],
)
def test_media_contract_rejects_invalid_inputs(filename, size_bytes, probe, error_code):
    with pytest.raises(RemakeError) as exc_info:
        RemakeMediaValidator.validate_probe(
            original_filename=filename,
            size_bytes=size_bytes,
            probe=probe,
            checksum="b" * 64,
            mime_type="application/octet-stream",
        )

    assert exc_info.value.error_code == error_code


def test_validate_path_hashes_file_and_uses_ffprobe_output(tmp_path, monkeypatch):
    source = tmp_path / "demo.mov"
    source.write_bytes(b"video-bytes")
    monkeypatch.setattr(
        "services.remake.media._run_ffprobe",
        lambda _: valid_probe("8.25"),
    )

    result = RemakeMediaValidator().validate_path(
        source,
        original_filename="demo.mov",
        mime_type="video/quicktime",
    )

    assert result.duration_seconds == 8.25
    assert len(result.checksum) == 64


def test_validate_path_maps_broken_ffprobe_to_stable_error(tmp_path, monkeypatch):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not-video")

    def fail(_: Path):
        raise OSError("ffprobe failed with secret path")

    monkeypatch.setattr("services.remake.media._run_ffprobe", fail)

    with pytest.raises(RemakeError) as exc_info:
        RemakeMediaValidator().validate_path(source, original_filename="broken.mp4")

    assert exc_info.value.error_code == "REMAKE_MEDIA_INVALID_CONTAINER"
    assert "secret" not in exc_info.value.message
