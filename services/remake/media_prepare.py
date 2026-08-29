from __future__ import annotations

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
    """返回全时长模型输入；仅超限时压缩，规则与参考复刻流水线一致。"""
    if not path.is_file():
        raise RuntimeError(f"视频文件不存在: {path}")
    if max_bytes <= 1024 * 1024:
        raise ValueError("模型视频输入上限必须大于 1 MiB")
    if max_width < 320:
        raise ValueError("模型视频输入最大宽度不能小于 320")
    if fps <= 0:
        raise ValueError("模型视频输入帧率必须大于 0")
    if path.stat().st_size <= max_bytes:
        return path

    stat = path.stat()
    fingerprint = sha256(
        (
            f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:"
            f"{max_bytes}:{max_width}:{fps:g}"
        ).encode("utf-8")
    ).hexdigest()[:12]
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"{path.stem}-{fingerprint}.mp4"
    if output.is_file() and output.stat().st_size <= max_bytes:
        return output

    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(probe.stdout.strip())
    except FileNotFoundError as error:
        raise RuntimeError("找不到 ffprobe，无法准备模型视频输入") from error
    except (subprocess.CalledProcessError, ValueError) as error:
        raise RuntimeError(f"读取模型视频输入时长失败: {path}") from error
    if duration <= 0:
        raise RuntimeError(f"模型视频输入时长无效: {path}")

    audio_bitrate = 96_000
    total_bitrate = int(max_bytes * 8 / duration * 0.92)
    video_bitrate = max(250_000, total_bitrate - audio_bitrate)
    temporary = output.with_name(f"{output.stem}.tmp.mp4")
    for _attempt in range(3):
        temporary.unlink(missing_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            f"scale=min({max_width}\\,iw):-2:flags=lanczos,fps={fps:g}",
            "-c:v",
            "libx264",
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
            raise RuntimeError("找不到 ffmpeg，无法压缩模型视频输入") from error
        except subprocess.CalledProcessError as error:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"压缩模型视频输入失败: {error.stderr}") from error
        actual_bytes = temporary.stat().st_size
        if actual_bytes <= max_bytes:
            temporary.replace(output)
            return output
        video_bitrate = max(
            250_000,
            int(video_bitrate * max_bytes / actual_bytes * 0.9),
        )

    temporary.unlink(missing_ok=True)
    raise RuntimeError("模型视频输入压缩 3 次后仍超过配置上限")
