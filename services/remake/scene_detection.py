from __future__ import annotations

from utils.messages import localized_message
from services.remake.production_timing import production_ranges, whole_second

from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import json
import shlex
import subprocess

import asyncio

import cv2
from scenedetect import ContentDetector, SceneManager
from scenedetect.backends.opencv import VideoCaptureAdapter
from scenedetect.scene_detector import FlashFilter
from scenedetect.video_splitter import DEFAULT_FFMPEG_ARGS

MAX_SCENE_SECONDS = 15.0
MIN_SCENE_SECONDS = 4.0


class RemakeSceneDetectionError(RuntimeError):
    pass


class SceneDetector:
    """与参考复刻流水线一致的 ContentDetector 镜头检测和切分。"""

    def __init__(self, shot_limit=None):
        self.shot_limit = shot_limit
        self.source_cuts = []
        self.source_start = 0.0

    def interval(self, a, b):
        start, end = a.get_seconds(), b.get_seconds()
        interval = {"start_seconds": start, "end_seconds": end}
        if self.shot_limit is not None:
            interval["output_seconds"] = max(1, whole_second(end - self.source_start) - whole_second(start - self.source_start))
            interval["internal_cuts"] = [t for t in self.source_cuts if start < t < end]
        return interval

    def detect(self, video_path: Path) -> list[tuple[Any, Any]]:
        capture = cv2.VideoCapture(
            str(video_path), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1]
        )
        try:
            video = VideoCaptureAdapter(capture)
            manager = SceneManager()
            manager.add_detector(
                ContentDetector(
                    threshold=27.0,
                    min_scene_len=max(1, round(video.frame_rate * min(MIN_SCENE_SECONDS, self.shot_limit or MIN_SCENE_SECONDS))),
                    filter_mode=FlashFilter.Mode.SUPPRESS,
                )
            )
            manager.detect_scenes(video)
            detected = manager.get_scene_list(start_in_scene=True)
            if self.shot_limit is None:
                return limit_scene_lengths(detected)
            self.source_start = detected[0][0].get_seconds() if detected else 0.0
            self.source_cuts = [s.get_seconds() for s, _ in detected[1:]]
            return production_ranges(detected, self.shot_limit)
        finally:
            capture.release()

    def split(self, video_path: Path, output_dir: Path) -> list[Path]:
        scenes = self.detect(video_path)
        if not scenes:
            raise RemakeSceneDetectionError("来源视频没有可分析的镜头")
        output_dir.mkdir(parents=True, exist_ok=True)
        return self._encode_ranges(video_path, output_dir, scenes)

    def split_timeline(self, video_path: Path, output_dir: Path) -> list[Path]:
        """Encode contiguous cuts in one pass and keep the original half-open source intervals."""
        scenes = self.detect(video_path)
        if not scenes:
            raise RemakeSceneDetectionError(localized_message('来源视频没有可分析的镜头'))
        output_dir.mkdir(parents=True, exist_ok=True)
        if len(scenes) == 1 or scenes[0][0].get_seconds() != 0 or any(
            end != next_start for (_, end), (next_start, _) in zip(scenes, scenes[1:])
        ):
            return self._encode_ranges(video_path, output_dir, scenes)
        with TemporaryDirectory(dir=output_dir) as temp:
            pattern = Path(temp) / "scene-%03d.mp4"
            command = self._segment_command(video_path, scenes, pattern)
            try:
                result = subprocess.run(command, capture_output=True)
            except OSError as error:
                raise RemakeSceneDetectionError(localized_message('视频镜头切分失败')) from error
            paths = [Path(temp) / f"scene-{i:03d}.mp4" for i in range(1, len(scenes) + 1)]
            if result.returncode or not all(path.is_file() and path.stat().st_size for path in paths):
                return self._encode_ranges(video_path, output_dir, scenes)
            paths = [path.replace(output_dir / path.name) for path in paths]
        self._write_boundaries(output_dir, paths, scenes)
        return paths

    @staticmethod
    def _segment_command(video_path, scenes, pattern, *listing):
        cuts = ",".join(f"{start.get_seconds():.9f}" for start, _ in scenes[1:])
        return ["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "1", "-i", str(video_path),
                       "-t", str(scenes[-1][1].get_seconds()), *shlex.split(DEFAULT_FFMPEG_ARGS), "-sn",
                       "-threads", "1", "-filter_threads", "1", "-force_key_frames", cuts,
                       "-f", "segment", "-segment_times", cuts, "-segment_time_delta",
                       str(0.5 / scenes[0][0].get_framerate()), "-segment_start_number", "1",
                       "-reset_timestamps", "1", *listing, str(pattern)]

    async def ready_clips(self, video_path, output_dir):
        """Publish only closed, nonempty segments while ffmpeg continues encoding later shots."""
        from services.remake.media_capacity import finish_thread
        scenes = await finish_thread(self.detect, video_path)
        if not scenes:
            raise RemakeSceneDetectionError(localized_message('来源视频没有可分析的镜头'))
        output_dir.mkdir(parents=True, exist_ok=True)
        total = len(scenes)
        bounds = [self.interval(a,b) for a, b in scenes]
        contiguous = scenes[0][0].get_seconds() == 0 and all(
            end == start for (_, end), (start, _) in zip(scenes, scenes[1:]))
        if total > 1 and contiguous:
            paths = []
            with TemporaryDirectory(dir=output_dir) as temp:
                pattern = Path(temp) / "scene-%03d.mp4"
                command = self._segment_command(video_path, scenes, pattern, "-segment_list", "pipe:1",
                                                "-segment_list_type", "flat")
                try:
                    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
                                                                   stderr=asyncio.subprocess.DEVNULL)
                except OSError as error:
                    raise RemakeSceneDetectionError(localized_message('视频镜头切分失败')) from error
                try:
                    async for line in process.stdout:
                        index = len(paths)
                        name = f"scene-{index+1:03d}.mp4"
                        src = Path(temp) / name
                        if index >= total or Path(line.decode().strip()).name != name or not src.is_file() or not src.stat().st_size:
                            raise RemakeSceneDetectionError(localized_message('视频镜头切分结果不完整'))
                        paths.append(src.replace(output_dir / name))
                        yield paths[-1], bounds[index], total
                    code = await process.wait()
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.communicate()
            if code == 0 and len(paths) == total:
                self._write_boundaries(output_dir, paths, scenes)
                return
            if paths:
                raise RemakeSceneDetectionError(localized_message('视频镜头切分结果不完整'))
        paths = await finish_thread(self._encode_ranges, video_path, output_dir, scenes)
        for path, bound in zip(paths, bounds, strict=True):
            yield path, bound, total

    def _encode_ranges(self, video_path, output_dir, scenes):
        paths = []
        for index, (start, end) in enumerate(scenes, start=1):
            destination = output_dir / f"scene-{index:03d}.mp4"
            # PySceneDetect's arg_override is output-only; decoder limits must precede -i.
            command = [
                "ffmpeg", "-v", "error", "-nostdin", "-y",
                "-ss", str(start.get_seconds()), "-threads", "1", "-i", str(video_path),
                "-t", str((end - start).get_seconds()),
                *shlex.split(DEFAULT_FFMPEG_ARGS),
                "-threads", "1", "-filter_threads", "1", "-sn", str(destination),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except (OSError, subprocess.CalledProcessError) as error:
                raise RemakeSceneDetectionError(localized_message('视频镜头切分失败')) from error
            paths.append(destination)
        if any(not path.is_file() or path.stat().st_size == 0 for path in paths):
            raise RemakeSceneDetectionError(localized_message('视频镜头切分结果不完整'))
        self._write_boundaries(output_dir, paths, scenes)
        return paths

    def _write_boundaries(self, output_dir, paths, scenes):
        (output_dir / "boundaries.json").write_text(json.dumps({
            path.name: self.interval(start, end)
            for path, (start, end) in zip(paths, scenes, strict=True)
        }))


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
