from pathlib import Path

import pytest

from services.remake.scene_detection import (
    RemakeSceneDetectionError,
    SceneDetector,
    limit_scene_lengths,
)


class Timecode:
    def __init__(self, seconds: float):
        self.seconds = seconds

    def __sub__(self, other):
        return Timecode(self.seconds - other.seconds)

    def __add__(self, seconds: float):
        return Timecode(self.seconds + seconds)


def test_scene_limits_match_reference_pipeline_exactly():
    scenes = limit_scene_lengths([(Timecode(0), Timecode(34))])

    assert [(end - start).seconds for start, end in scenes] == [15, 15, 4]


def test_short_final_scene_is_merged_before_long_scene_limiting():
    scenes = limit_scene_lengths(
        [(Timecode(0), Timecode(8)), (Timecode(8), Timecode(10))]
    )

    assert [(end - start).seconds for start, end in scenes] == [10]


def test_detector_rejects_empty_or_incomplete_split_results(monkeypatch, tmp_path):
    detector = SceneDetector()
    monkeypatch.setattr(detector, "detect", lambda _path: [])

    with pytest.raises(RemakeSceneDetectionError, match="没有可分析的镜头"):
        detector.split(Path("source.mp4"), tmp_path)


def test_detector_sorts_paths_and_requires_one_file_per_scene(monkeypatch, tmp_path):
    detector = SceneDetector()
    monkeypatch.setattr(
        detector,
        "detect",
        lambda _path: [(Timecode(0), Timecode(5)), (Timecode(5), Timecode(10))],
    )
    monkeypatch.setattr(
        "services.remake.scene_detection.split_video_ffmpeg",
        lambda *_args, **_kwargs: (tmp_path / "scene-002.mp4").write_bytes(b"video"),
    )

    with pytest.raises(RemakeSceneDetectionError, match="切分结果不完整"):
        detector.split(Path("source.mp4"), tmp_path)
