from __future__ import annotations

from utils.messages import localized_message

import json
import subprocess
from hashlib import sha256
from pathlib import Path


def prepare_video_for_model_input(
    path: Path,
    cache_dir: Path,
    *,
    max_bytes: int,
    max_width: int = 1280,
    fps: float = 15,
) -> Path:
    """返回全时长模型输入，限制文件大小及画面长边。"""
    if not path.is_file():
        raise RuntimeError(localized_message('视频文件不存在: {p1}', p1=f'{path}'))
    if max_bytes <= 1024 * 1024:
        raise ValueError(localized_message('模型视频输入上限必须大于 1 MiB'))
    if max_width < 320:
        raise ValueError(localized_message('模型视频输入最大宽度不能小于 320'))
    if fps <= 0:
        raise ValueError(localized_message('模型视频输入帧率必须大于 0'))
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "format=duration:stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        metadata = json.loads(probe.stdout)
        duration = float(metadata['format']['duration'])
    except FileNotFoundError as error:
        raise RuntimeError(localized_message('找不到 ffprobe，无法准备模型视频输入')) from error
    except (subprocess.CalledProcessError, ValueError) as error:
        raise RuntimeError(localized_message('读取模型视频输入时长失败: {p1}', p1=f'{path}')) from error
    if duration <= 0:
        raise RuntimeError(localized_message('模型视频输入时长无效: {p1}', p1=f'{path}'))

    stat = path.stat()
    stream = metadata['streams'][0]
    if stat.st_size <= max_bytes and max(stream['width'], stream['height']) <= max_width:
        return path
    fingerprint = sha256(
        f"bounded-v2:{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{max_bytes}:{max_width}:{fps:g}".encode()
    ).hexdigest()[:12]
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"{path.stem}-{fingerprint}.mp4"
    if output.is_file() and output.stat().st_size <= max_bytes:
        return output

    audio_bitrate = 96_000
    total_bitrate = int(min(max_bytes, stat.st_size) * 8 / duration * 0.92)
    video_bitrate = max(250_000, total_bitrate - audio_bitrate)
    temporary = output.with_name(f"{output.stem}.tmp.mp4")
    for _attempt in range(3):
        temporary.unlink(missing_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"fps={fps:g},scale=min({max_width}\\,iw):min({max_width}\\,ih):force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-b:v",
            str(video_bitrate),
            "-maxrate",
            str(video_bitrate),
            "-bufsize",
            str(video_bitrate * 2),
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            str(temporary),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as error:
            raise RuntimeError(localized_message('找不到 ffmpeg，无法压缩模型视频输入')) from error
        except subprocess.CalledProcessError as error:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(localized_message('压缩模型视频输入失败: {p1}', p1=f'{error.stderr}')) from error
        actual_bytes = temporary.stat().st_size
        if actual_bytes <= max_bytes:
            temporary.replace(output)
            return output
        video_bitrate = max(
            250_000,
            int(video_bitrate * max_bytes / actual_bytes * 0.9),
        )

    temporary.unlink(missing_ok=True)
    raise RuntimeError(localized_message('模型视频输入压缩 3 次后仍超过配置上限'))
