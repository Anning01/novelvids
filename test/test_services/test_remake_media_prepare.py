from pathlib import Path

import pytest

from services.remake.media_prepare import prepare_video_for_model_input


def test_model_input_reuses_source_when_already_under_limit(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    result = prepare_video_for_model_input(
        source,
        tmp_path / "cache",
        max_bytes=1024 * 1024 + 1,
    )

    assert result == source


@pytest.mark.parametrize(
    ("max_bytes", "max_width", "fps", "message"),
    [
        (1024, 1280, 15, "上限必须大于"),
        (2 * 1024 * 1024, 100, 15, "最大宽度不能小于"),
        (2 * 1024 * 1024, 1280, 0, "帧率必须大于"),
    ],
)
def test_model_input_rejects_invalid_preparation_rules(
    tmp_path, max_bytes, max_width, fps, message
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    with pytest.raises(ValueError, match=message):
        prepare_video_for_model_input(
            source,
            tmp_path / "cache",
            max_bytes=max_bytes,
            max_width=max_width,
            fps=fps,
        )
