"""把历史项目的一集严格固化为与原项目解耦的来源视频。"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from config import settings
from exceptions.remake import RemakeError
from models.chapter import Chapter
from services.oss import oss
from services.remake.history import RemakeHistoryCatalog, remake_history_catalog
from services.remake.media import RemakeMediaValidator, ValidatedRemakeMedia
from services.video.merge import VideoMerger, video_merger


@dataclass(frozen=True)
class HistorySnapshot:
    storage_provider: str
    object_key: str
    original_filename: str
    media: ValidatedRemakeMedia
    source_novel_id: int
    source_chapter_id: int
    manifest: dict


class RemakeHistorySnapshotService:
    """锁定当前视频版本、按顺序合成、校验并写入独立受控存储。"""

    def __init__(
        self,
        *,
        catalog: RemakeHistoryCatalog | None = None,
        merger: VideoMerger | None = None,
        validator: RemakeMediaValidator | None = None,
        provider=None,
        media_root: Path | str | None = None,
    ) -> None:
        self.catalog = catalog or remake_history_catalog
        self.merger = merger or video_merger
        self.validator = validator or RemakeMediaValidator()
        self.provider = provider or oss
        self.media_root = Path(media_root or settings.MEDIA_PATH).resolve()

    async def create(
        self,
        chapter: Chapter,
        *,
        team_id: int | None,
    ) -> HistorySnapshot:
        inspection = await self.catalog.inspect(chapter)
        if not inspection.available:
            raise RemakeError(
                422,
                "REMAKE_HISTORY_EPISODE_UNAVAILABLE",
                inspection.unavailable_reason or "该剧集暂不可重制",
                context={"source_chapter_id": chapter.id},
            )

        snapshot_id = uuid4()
        object_key = (
            f"remake/sources/history/{team_id or 0}/"
            f"{snapshot_id}.mp4"
        )
        original_filename = f"第{chapter.number}集-历史快照.mp4"
        destination = self._local_path(object_key)
        uploaded = False
        work_root = self.media_root / "remake" / ".snapshot-work"
        work_root.mkdir(parents=True, exist_ok=True)
        try:
            with TemporaryDirectory(prefix=f"{snapshot_id}-", dir=work_root) as directory:
                temporary_dir = Path(directory)
                paths: list[str] = []
                components: list[dict] = []
                for index, selected in enumerate(inspection.selected):
                    materialized = await self._materialize(
                        selected.video.url,
                        temporary_dir / f"{index:04d}-{selected.video.id}.mp4",
                    )
                    paths.append(str(materialized))
                    components.append(
                        {
                            "sequence": selected.scene.sequence,
                            "scene_id": selected.scene.id,
                            "video_id": selected.video.id,
                            "video_ref": selected.video.url,
                        }
                    )

                output = temporary_dir / "snapshot.mp4"
                await asyncio.to_thread(self.merger.merge_paths, paths, str(output))
                media = await asyncio.to_thread(
                    self.validator.validate_path,
                    output,
                    original_filename=original_filename,
                    mime_type="video/mp4",
                )
                if self.provider.enabled:
                    uploaded = True
                    await self.provider.put_file(object_key, output, "video/mp4")
                    storage_provider = "oss"
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(os.replace, output, destination)
                    storage_provider = "local"

            return HistorySnapshot(
                storage_provider=storage_provider,
                object_key=object_key,
                original_filename=original_filename,
                media=media,
                source_novel_id=chapter.novel_id,
                source_chapter_id=chapter.id,
                manifest={
                    "source_novel_id": chapter.novel_id,
                    "source_chapter_id": chapter.id,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "components": components,
                },
            )
        except Exception as error:
            destination.unlink(missing_ok=True)
            if self.provider.enabled and uploaded:
                try:
                    await self.provider.delete(object_key)
                except Exception:
                    pass
            raise RemakeError(
                500,
                "REMAKE_HISTORY_SNAPSHOT_FAILED",
                "历史剧集快照生成失败，请重试",
                context={"source_chapter_id": chapter.id},
                retryable=True,
            ) from error

    async def cleanup(self, snapshot: HistorySnapshot) -> None:
        if snapshot.storage_provider == "local":
            self._local_path(snapshot.object_key).unlink(missing_ok=True)
            return
        await self.provider.delete(snapshot.object_key)

    async def _materialize(self, raw_url: str | None, destination: Path) -> Path:
        raw = str(raw_url or "").split("?", 1)[0]
        relative = ""
        if raw.startswith("/media/"):
            relative = raw.removeprefix("/media/")
        elif raw.startswith("./media/"):
            relative = raw.removeprefix("./media/")
        if relative:
            local = self._local_path(relative)
            if local.is_file():
                return local

        if self.provider.enabled:
            object_key = self.provider.normalize_media_ref(raw)
            if object_key and object_key.startswith(("uploads/", "remake/")):
                await self.provider.download_to_file(object_key, destination)
                return destination
        raise FileNotFoundError("历史分镜视频文件不存在")

    def _local_path(self, object_key: str) -> Path:
        path = (self.media_root / object_key).resolve()
        if path != self.media_root and not path.is_relative_to(self.media_root):
            raise ValueError("媒体路径越界")
        return path


remake_history_snapshot_service = RemakeHistorySnapshotService()
