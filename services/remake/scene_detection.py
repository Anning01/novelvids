from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scenedetect import ContentDetector, SceneManager, open_video, split_video_ffmpeg
from scenedetect.scene_detector import FlashFilter

MAX_SCENE_SECONDS = 15.0
MIN_SCENE_SECONDS = 4.0


class RemakeSceneDetectionError(RuntimeError):
    pass


class SceneDetector:
    """与参考复刻流水线一致的 ContentDetector 镜头检测和切分。"""

    def detect(self, video_path: Path) -> list[tuple[Any, Any]]:
        video = open_video(str(video_path))
        manager = SceneManager()
        manager.add_detector(
            ContentDetector(
                threshold=27.0,
                min_scene_len=max(1, round(video.frame_rate * MIN_SCENE_SECONDS)),
                filter_mode=FlashFilter.Mode.SUPPRESS,
            )
        )
        manager.detect_scenes(video)
        return limit_scene_lengths(manager.get_scene_list())

    def split(self, video_path: Path, output_dir: Path) -> list[Path]:
        scenes = self.detect(video_path)
        if not scenes:
            raise RemakeSceneDetectionError("来源视频没有可分析的镜头")
        output_dir.mkdir(parents=True, exist_ok=True)
        split_video_ffmpeg(
            str(video_path),
            scenes,
            output_dir=output_dir,
            output_file_template="scene-$SCENE_NUMBER.mp4",
        )
        paths = sorted(output_dir.glob("scene-*.mp4"))
        if len(paths) != len(scenes):
            raise RemakeSceneDetectionError("视频镜头切分结果不完整")
        return paths


def limit_scene_lengths(scenes: Iterable[Any]) -> list[tuple[Any, Any]]:
    """合并不足 4 秒的尾镜头，并把长镜头切成最长 15 秒。"""
    normalized = list(scenes)
    if len(normalized) > 1 and _duration_seconds(*normalized[-1]) < MIN_SCENE_SECONDS:
        normalized[-2:] = [(normalized[-2][0], normalized[-1][1])]
    result: list[tuple[Any, Any]] = []
    for start, end in normalized:
        cursor = start
        while _duration_seconds(cursor, end) > MAX_SCENE_SECONDS:
            next_end = _shift_seconds(cursor, MAX_SCENE_SECONDS)
            if _duration_seconds(next_end, end) < MIN_SCENE_SECONDS:
                next_end = _shift_seconds(end, -MIN_SCENE_SECONDS)
            result.append((cursor, next_end))
            cursor = next_end
        result.append((cursor, end))
    return result


def _duration_seconds(start: Any, end: Any) -> float:
    if callable(getattr(start, "get_seconds", None)) and callable(
        getattr(end, "get_seconds", None)
    ):
        return float(end.get_seconds()) - float(start.get_seconds())
    return float((end - start).seconds)


def _shift_seconds(timecode: Any, seconds: float) -> Any:
    get_framerate = getattr(timecode, "get_framerate", None)
    if callable(get_framerate):
        return timecode + round(seconds * float(get_framerate()))
    return timecode + seconds


scene_detector = SceneDetector()
