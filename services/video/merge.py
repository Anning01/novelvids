"""视频合并服务 - 使用 FFmpeg concat filter 合并多个视频。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from models.video import Video

logger = logging.getLogger(__name__)


def _check_audio_stream(video_path: str) -> bool:
    """检查视频文件是否包含音频流。"""
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'default=noprint_wrappers=1', video_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return max(0.01, float(result.stdout.strip()))
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.01


class VideoMerger:
    """视频合并器 - 将多个视频按顺序合并为一个。"""

    def __init__(self):
        self.output_dir = os.path.join(settings.MEDIA_PATH, "videos", "merged")
        os.makedirs(self.output_dir, exist_ok=True)

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
            raise ValueError("当前没有可合并的视频")

        # 收集所有视频文件路径
        video_paths = []
        for video in videos:
            path = self._get_video_path(video)
            if not path:
                raise ValueError(f"视频文件不存在: video_id={video.id}")
            # Windows 路径处理：转换为绝对路径并规范化
            abs_path = os.path.abspath(path)
            video_paths.append(abs_path)

        # 生成输出文件名
        if output_filename is None:
            output_filename = f"chapter_{chapter_id}_merged.mp4"

        os.makedirs(self.output_dir, exist_ok=True)
        output_path = os.path.abspath(os.path.join(self.output_dir, output_filename))

        # 一个分镜时仍产出统一的“章节完整视频”文件，页面无需区分下载路径。
        if len(video_paths) == 1:
            shutil.copyfile(video_paths[0], output_path)
            return f"/media/videos/merged/{output_filename}"

        # 两个及以上片段才需要检测音轨并调用 FFmpeg。
        has_audio_list = [_check_audio_stream(path) for path in video_paths]

        # 构建 FFmpeg 命令 - 根据是否有音频决定 filter
        input_args = []
        filter_parts = []

        if all(has_audio_list):
            # 所有视频都有音频 - 标准模式
            for i, path in enumerate(video_paths):
                input_args.extend(['-i', path])
                filter_parts.append(f'[{i}:v][{i}:a]')
            filter_complex = ''.join(filter_parts) + f'concat=n={len(video_paths)}:v=1:a=1[outv][outa]'
            cmd = [
                'ffmpeg', '-y'
            ] + input_args + [
                '-filter_complex', filter_complex,
                '-map', '[outv]',
                '-map', '[outa]',
                output_path
            ]
        elif not any(has_audio_list):
            # 所有视频都没有音频 - 纯视频合并
            for i, path in enumerate(video_paths):
                input_args.extend(['-i', path])
                filter_parts.append(f'[{i}:v]')
            filter_complex = ''.join(filter_parts) + f'concat=n={len(video_paths)}:v=1:a=0[v]'
            cmd = [
                'ffmpeg', '-y'
            ] + input_args + [
                '-filter_complex', filter_complex,
                '-map', '[v]',
                output_path
            ]
        else:
            # 混合情况 - 添加静音音频流
            for i, (path, has_audio) in enumerate(zip(video_paths, has_audio_list)):
                input_args.extend(['-i', path])
                filter_parts.append(f'[{i}:v:0]setpts=PTS-STARTPTS[v{i}];')
                if has_audio:
                    filter_parts.append(
                        f'[{i}:a:0]aformat=sample_rates=44100:channel_layouts=stereo,'
                        f'asetpts=PTS-STARTPTS[a{i}];'
                    )
                else:
                    # 没有音频的视频，用 anullsrc 添加静音
                    duration = _probe_duration(path)
                    filter_parts.append(
                        f'anullsrc=channel_layout=stereo:sample_rate=44100,'
                        f'atrim=duration={duration},asetpts=PTS-STARTPTS[a{i}];'
                    )

            concat_inputs = ''.join(f'[v{i}][a{i}]' for i in range(len(video_paths)))
            filter_complex = ''.join(filter_parts) + concat_inputs + f'concat=n={len(video_paths)}:v=1:a=1[outv][outa]'
            cmd = [
                'ffmpeg', '-y'
            ] + input_args + [
                '-filter_complex', filter_complex,
                '-map', '[outv]',
                '-map', '[outa]',
                output_path
            ]

        # Windows 命令行长度限制检查 (约 8000 字符安全边界)
        cmd_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
        if len(cmd_str) > 8000:
            raise RuntimeError(f"视频数量过多（{len(video_paths)}个），命令行超过Windows限制，请分批合并")

        # 执行合并
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg returncode: {result.returncode}")
            logger.error(f"FFmpeg stderr: {result.stderr}")
            logger.error(f"FFmpeg stdout: {result.stdout}")
            raise RuntimeError(f"视频合并失败: {result.stderr}")

        # 验证输出文件是否真的创建成功
        if not os.path.exists(output_path):
            logger.error(f"Output file not created: {output_path}")
            logger.error(f"FFmpeg stdout: {result.stdout}")
            logger.error(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"视频合并失败：输出文件未创建")

        return f"/media/videos/merged/{output_filename}"


video_merger = VideoMerger()
