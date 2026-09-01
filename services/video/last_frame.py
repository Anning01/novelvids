"""生成视频尾帧的统一持久化服务。

供应商没有返回尾帧时，从已经持久化的成片中提取最后一帧。OSS 模式下，
视频读取和尾帧写入都经过 OSSProvider 的服务端接口（阿里云实现为内网 endpoint）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from config import settings
from services.oss import make_upload_key, oss
from services.video.source import VideoSourceError, materialize_video_source


logger = logging.getLogger(__name__)


class LastFrameExtractionError(RuntimeError):
    """尾帧无法从成片提取或持久化。"""


class LastFrameService:
    """将本地、OSS 或远程成片物化后，通过 FFmpeg 提取并保存尾帧。"""

    async def extract_and_store(
        self,
        video_ref: str,
        video_id: int,
        *,
        team_id: int | None = None,
    ) -> str:
        if not video_ref.strip():
            raise LastFrameExtractionError("视频地址为空，无法提取尾帧")

        with TemporaryDirectory(prefix=f"novelvids-last-frame-{video_id}-") as directory:
            temporary_dir = Path(directory)
            video_path = await self._materialize_video(
                video_ref,
                temporary_dir / "source.mp4",
            )
            frame_path = temporary_dir / f"last-frame-{video_id}.png"
            await asyncio.to_thread(self._extract_with_ffmpeg, video_path, frame_path)

            if oss.enabled:
                key = make_upload_key(
                    team_id,
                    f"video-references/last-frame-{video_id}.png",
                )
                # 云 Provider 在这里使用内网 endpoint 流式上传。
                await oss.put_file(key, frame_path, "image/png")
                return key

            destination_dir = Path(settings.MEDIA_PATH) / "video-references"
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / frame_path.name
            await asyncio.to_thread(os.replace, frame_path, destination)
            return f"/media/video-references/{destination.name}"

    async def _materialize_video(self, video_ref: str, destination: Path) -> Path:
        try:
            return await materialize_video_source(
                video_ref,
                destination,
                media_root=Path(settings.MEDIA_PATH),
                oss_provider=oss,
            )
        except VideoSourceError as exc:
            raise LastFrameExtractionError(f"{exc}，无法提取尾帧") from exc

    @staticmethod
    def _local_media_path(video_ref: str) -> Path | None:
        raw_path = video_ref.split("?", 1)[0]
        if not raw_path.startswith("/media/"):
            return None
        media_root = Path(settings.MEDIA_PATH).resolve()
        candidate = (media_root / raw_path.removeprefix("/media/")).resolve()
        if not candidate.is_relative_to(media_root) or not candidate.is_file():
            raise LastFrameExtractionError("本地视频文件不存在，无法提取尾帧")
        return candidate

    @staticmethod
    def _extract_with_ffmpeg(video_path: Path, frame_path: Path) -> None:
        # 只解码最后一秒并反转该片段，第一张输出图就是视频的真实最后一帧；
        # 避免 reverse 过滤器缓存整段最长 30 秒、2K 视频。
        command = [
            "ffmpeg",
            "-y",
            "-sseof",
            "-1",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "reverse",
            "-frames:v",
            "1",
            str(frame_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LastFrameExtractionError("FFmpeg 提取视频尾帧失败") from exc
        if result.returncode != 0 or not frame_path.is_file() or frame_path.stat().st_size == 0:
            logger.warning(
                "ffmpeg_last_frame_failed returncode=%s stderr=%s",
                result.returncode,
                result.stderr[-500:],
            )
            raise LastFrameExtractionError("FFmpeg 提取视频尾帧失败")


last_frame_service = LastFrameService()
