"""视频合并服务 - 使用 FFmpeg concat filter 合并多个视频。"""

from __future__ import annotations

from services.media_processing import run_media

from utils.messages import localized_message

import asyncio
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from config import settings
from services.oss import oss

if TYPE_CHECKING:
    from models.video import Video

logger = logging.getLogger(__name__)


def _check_audio_stream(video_path: str) -> bool:
    """检查视频文件是否包含音频流。"""
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'default=noprint_wrappers=1', video_path]
    try:
        result = run_media(cmd, capture_output=True, text=True, timeout=10)
        # 如果有输出，说明有音频流
        return bool(result.stdout.strip())
    except Exception:
        return False


def _probe_duration(video_path: str) -> float:
    """读取视频时长，为无音轨片段生成等长静音。"""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ]
    try:
        result = run_media(cmd, capture_output=True, text=True, timeout=10)
        return max(0.01, float(result.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.01


def _video_dimensions(video_path: str) -> tuple[int, int]:
    from services.video.reference_media import _probe, _video_stream
    stream = _video_stream(_probe(Path(video_path)))
    return int(stream['width']), int(stream['height'])


def _video_frame_rate(video_path: str) -> float:
    from services.video.reference_media import _probe, _video_stream, _fps
    rate = _fps(_video_stream(_probe(Path(video_path))))
    if not rate:
        raise ValueError(localized_message('无法读取视频帧率'))
    return rate


class VideoMerger:
    """视频合并器 - 将多个视频按顺序合并为一个。"""

    def __init__(self):
        self.output_dir = os.path.join(settings.MEDIA_PATH, "videos", "merged")
        os.makedirs(self.output_dir, exist_ok=True)
        self._merge_lock = threading.Lock()

    def _get_video_path(self, video: Video) -> str | None:
        """获取视频文件的本地路径。

        Args:
            video: 视频记录

        Returns:
            本地文件路径，如果文件不存在返回 None
        """
        media_root = Path(settings.MEDIA_PATH).resolve()
        raw_url = str(video.url or "").split("?", 1)[0]
        relative_path = ""
        if raw_url.startswith("/media/"):
            relative_path = raw_url.removeprefix("/media/")
        elif raw_url.startswith("./media/"):
            relative_path = raw_url.removeprefix("./media/")
        if relative_path:
            candidate = (media_root / relative_path).resolve()
            if candidate.is_relative_to(media_root) and candidate.is_file():
                return str(candidate)

        video_path = media_root / "videos" / f"{video.id}.mp4"
        if video_path.is_file():
            return str(video_path)
        return None

    def merge_videos(
        self,
        videos: list[Video],
        chapter_id: int,
        output_filename: str | None = None
    ) -> str:
        """合并多个视频为一个文件。

        Args:
            videos: 要合并的视频列表（按顺序）
            chapter_id: 章节 ID
            output_filename: 输出文件名，默认为 "chapter_{chapter_id}_merged.mp4"

        Returns:
            合并后的视频 URL (如 /media/videos/merged/xxx.mp4)

        Raises:
            ValueError: 没有视频或视频文件不存在
            RuntimeError: FFmpeg 执行失败
        """
        if not videos:
            raise ValueError(localized_message('当前没有可合并的视频'))

        # 收集所有视频文件路径
        video_paths = []
        for video in videos:
            path = self._get_video_path(video)
            if not path:
                raise ValueError(localized_message('视频文件不存在: video_id={p1}', p1=f'{video.id}'))
            # Windows 路径处理：转换为绝对路径并规范化
            abs_path = os.path.abspath(path)
            video_paths.append(abs_path)

        # 生成输出文件名
        if output_filename is None:
            output_filename = f"chapter_{chapter_id}_merged.mp4"

        os.makedirs(self.output_dir, exist_ok=True)
        output_path = os.path.abspath(os.path.join(self.output_dir, output_filename))
        self._merge_video_paths(video_paths, output_path)
        return f"/media/videos/merged/{output_filename}"

    async def merge_videos_from_storage(
        self,
        videos: list[Video],
        chapter_id: int,
        *,
        team_id: int | None = None,
    ) -> str:
        """合并本地或 OSS 视频；OSS 读写始终使用 Provider 的服务端端点。"""
        if not videos:
            raise ValueError(localized_message('当前没有可合并的视频'))

        if not oss.enabled:
            return await asyncio.to_thread(self.merge_videos, videos, chapter_id)

        output_filename = f"chapter_{chapter_id}_merged.mp4"
        # /tmp may be tmpfs on small servers; large source videos belong on the media volume.
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=self.output_dir, prefix=f".storage-merge-{chapter_id}-") as directory:
            temporary_dir = Path(directory)
            video_paths: list[str] = []

            for index, video in enumerate(videos):
                local_path = self._get_video_path(video)
                if local_path:
                    video_paths.append(os.path.abspath(local_path))
                    continue

                raw_url = str(video.url or "")
                object_key = oss.normalize_media_ref(raw_url)
                if not object_key or not object_key.startswith("uploads/"):
                    raise ValueError(localized_message('视频文件不存在: video_id={p1}', p1=f'{video.id}'))

                destination = temporary_dir / f"{index:04d}-{video.id}.mp4"
                try:
                    await oss.download_to_file(object_key, destination)
                except Exception as exc:
                    logger.exception("OSS video download failed: video_id=%s", video.id)
                    raise RuntimeError(
                        localized_message('从 OSS 读取视频失败: video_id={p1}', p1=f'{video.id}')
                    ) from exc
                video_paths.append(str(destination))

            output_path = temporary_dir / output_filename
            await asyncio.to_thread(
                self._merge_video_paths,
                video_paths,
                str(output_path),
            )

            output_key = (
                f"uploads/{team_id or 0}/videos/merged/{output_filename}"
            )
            try:
                await oss.put_file(output_key, output_path, "video/mp4")
            except Exception as exc:
                logger.exception("OSS merged video upload failed: chapter_id=%s", chapter_id)
                raise RuntimeError(localized_message('合并视频上传 OSS 失败')) from exc

            return oss.resolve_url(output_key) or output_key

    def _merge_video_paths(self, video_paths: list[str], output_path: str) -> None:
        # Bound concurrent encoders and publish only a complete file on the media volume.
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._merge_lock, TemporaryDirectory(dir=destination.parent, prefix='.merge-') as directory:
            staged = Path(directory) / 'complete.mp4'
            self._render_video_paths(video_paths, str(staged))
            staged.chmod(0o644)
            os.replace(staged, destination)

    def _render_video_paths(self, video_paths: list[str], output_path: str) -> None:
        """将已物化的本地视频合并到指定路径。"""
        if not video_paths:
            raise ValueError(localized_message('当前没有可合并的视频'))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 一个分镜时仍产出统一的“章节完整视频”文件，页面无需区分下载路径。
        if len(video_paths) == 1:
            shutil.copyfile(video_paths[0], output_path)
            return

        # Normalize one clip at a time: a chapter must not keep every HD decoder in memory.
        sizes = [_video_dimensions(path) for path in video_paths]
        width, height = max(sizes, key=lambda size: size[0] * size[1])
        width += width % 2
        height += height % 2
        audio_states = [_check_audio_stream(path) for path in video_paths]
        include_audio = any(audio_states)
        fps = _video_frame_rate(video_paths[0])
        staged = Path(output_path).parent
        segments = []
        for index, (path, has_audio) in enumerate(zip(video_paths, audio_states)):
            segment = staged / f'segment-{index:04d}.mp4'
            duration = _probe_duration(path)
            cmd = ['ffmpeg', '-v', 'error', '-nostdin', '-y', '-filter_threads', '1',
                   '-threads', '1', '-i', path]
            if include_audio and not has_audio:
                cmd += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100']
            cmd += ['-map', '0:v:0', '-vf',
                    f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                    f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}',
                    # A short encoder lookahead bounds RAM; CRF 18 preserves detail during normalization.
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-threads', '2']
            if include_audio:
                cmd += ['-map', '0:a:0' if has_audio else '1:a:0', '-af', 'apad',
                        '-c:a', 'aac', '-ar', '44100', '-ac', '2']
            else:
                cmd += ['-an']
            cmd += ['-t', str(duration), str(segment)]
            self._run_merge_command(cmd)
            segments.append(segment)
        manifest = staged / 'segments.txt'
        manifest.write_text(''.join(f"file '{segment.name}'\n" for segment in segments), encoding='utf-8')
        self._run_merge_command(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'concat',
                                 '-safe', '0', '-i', str(manifest), '-c', 'copy',
                                 '-movflags', '+faststart', output_path])

    @staticmethod
    def _run_merge_command(command: list[str]) -> None:
        result = run_media(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=1200)
        if result.returncode != 0:
            logger.error('Video merge failed: returncode=%s', result.returncode)
            raise RuntimeError(localized_message('视频合并失败: {p1}', p1=result.stderr[-4000:]))
        output = Path(command[-1])
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError(localized_message('视频合并失败：输出文件未创建'))

    def merge_paths(self, video_paths: list[str], output_path: str) -> None:
        """合并调用方已物化的媒体文件，供不可变快照等服务复用。"""
        self._merge_video_paths(video_paths, output_path)

video_merger = VideoMerger()
