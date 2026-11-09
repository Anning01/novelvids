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

    def get_seconds(self):
        return self.seconds


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
        "services.remake.scene_detection.subprocess.run",
        lambda *_args, **_kwargs: (tmp_path / "scene-002.mp4").write_bytes(b"video"),
    )

    with pytest.raises(RemakeSceneDetectionError, match="切分结果不完整"):
        detector.split(Path("source.mp4"), tmp_path)


@pytest.mark.parametrize("fails", [False, True])
def test_detection_bounds_decoder_threads_and_releases_capture(monkeypatch, fails):
    from unittest.mock import Mock
    import cv2

    capture = Mock()
    video = Mock(frame_rate=30)
    manager = Mock()
    manager.get_scene_list.return_value = []
    if fails:
        manager.detect_scenes.side_effect = RuntimeError("decode failed")
    monkeypatch.setattr("services.remake.scene_detection.cv2.VideoCapture", capture)
    monkeypatch.setattr("services.remake.scene_detection.VideoCaptureAdapter", lambda cap: video)
    monkeypatch.setattr("services.remake.scene_detection.SceneManager", lambda: manager)

    if fails:
        with pytest.raises(RuntimeError, match="decode failed"):
            SceneDetector().detect(Path("source.mp4"))
    else:
        assert SceneDetector().detect(Path("source.mp4")) == []

    capture.assert_called_once_with("source.mp4", cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    capture.return_value.release.assert_called_once()


def test_split_limits_input_and_output_threads_without_changing_quality(monkeypatch, tmp_path):
    from scenedetect import FrameTimecode
    commands = []
    scenes = [(FrameTimecode(0, 30), FrameTimecode(120, 30))]
    detector = SceneDetector()
    monkeypatch.setattr(detector, "detect", lambda _path: scenes)

    def run(command, **kwargs):
        commands.append(command)
        assert kwargs["check"] is True
        Path(command[-1]).write_bytes(b"video")

    monkeypatch.setattr("services.remake.scene_detection.subprocess.run", run)
    assert detector.split(Path("source with spaces.mp4"), tmp_path) == [tmp_path / "scene-001.mp4"]
    command = commands[0]
    input_index = command.index("-i")
    assert command[input_index - 2:input_index] == ["-threads", "1"]
    assert command[input_index + 1] == "source with spaces.mp4"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-crf") + 1] == "22"
    assert command[command.index("-filter_threads") + 1] == "1"
    assert command.count("-threads") == 2
    assert "-vf" not in command


@pytest.mark.parametrize("missing_binary", [False, True])
def test_failed_split_stops_before_processing_more_scenes(monkeypatch, tmp_path, missing_binary):
    import subprocess
    from unittest.mock import Mock

    detector = SceneDetector()
    monkeypatch.setattr(detector, "detect", lambda _: [
        (Timecode(0), Timecode(4)), (Timecode(4), Timecode(8)),
    ])
    failure = FileNotFoundError("ffmpeg") if missing_binary else subprocess.CalledProcessError(1, "ffmpeg")
    run = Mock(side_effect=failure)
    monkeypatch.setattr("services.remake.scene_detection.subprocess.run", run)
    with pytest.raises(RemakeSceneDetectionError, match="视频镜头切分失败"):
        detector.split(Path("source.mp4"), tmp_path)
    assert run.call_count == 1
