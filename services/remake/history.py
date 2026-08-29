"""历史项目章节可用性检查、权限范围目录与不可变快照。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from config import settings
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from services.remake.media import MAX_REMAKE_BYTES, MAX_REMAKE_DURATION_SECONDS
from utils.enums import TaskStatusEnum


@dataclass(frozen=True)
class HistorySelectedVideo:
    scene: Scene
    video: Video


@dataclass(frozen=True)
class HistoryEpisodeInspection:
    chapter: Chapter
    selected: tuple[HistorySelectedVideo, ...]
    duration_seconds: float
    size_bytes: int
    scene_count: int
    unavailable_reason: str | None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    def as_api_dict(self) -> dict:
        return {
            "chapter_id": self.chapter.id,
            "episode_number": self.chapter.number,
            "name": self.chapter.name,
            "duration_seconds": round(self.duration_seconds, 3),
            "size_bytes": self.size_bytes,
            "scene_count": self.scene_count,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


class RemakeHistoryCatalog:
    async def inspect(self, chapter: Chapter) -> HistoryEpisodeInspection:
        scenes = await Scene.filter(chapter_id=chapter.id).order_by("sequence", "id")
        if not scenes:
            return HistoryEpisodeInspection(chapter, (), 0.0, 0, 0, "章节暂无分镜")

        selected: list[HistorySelectedVideo] = []
        missing: list[int] = []
        total_duration = 0.0
        total_size = 0
        for scene in scenes:
            video = await self._current_completed_video(scene)
            if video is None:
                missing.append(scene.sequence)
                continue
            selected.append(HistorySelectedVideo(scene=scene, video=video))
            total_duration += max(0.0, float(scene.duration or 0))
            total_size += self._video_size(video)

        reason = None
        if missing:
            labels = "、".join(f"镜头 {sequence}" for sequence in missing)
            reason = f"{labels} 尚无已完成视频"
        elif total_duration > MAX_REMAKE_DURATION_SECONDS:
            reason = "章节成片超过20分钟"
        elif total_size > MAX_REMAKE_BYTES:
            reason = "章节成片预计超过500MB"
        return HistoryEpisodeInspection(
            chapter=chapter,
            selected=tuple(selected),
            duration_seconds=total_duration,
            size_bytes=total_size,
            scene_count=len(scenes),
            unavailable_reason=reason,
        )

    async def list_episodes(self, novel_id: int) -> list[dict]:
        chapters = await Chapter.filter(novel_id=novel_id).order_by("number", "id")
        return [(await self.inspect(chapter)).as_api_dict() for chapter in chapters]

    async def list_projects(
        self,
        *,
        team_id: int | None,
        allow_all: bool,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict:
        # 历史来源只允许来自短剧制作，避免把重制项目再次作为重制源。
        query = Novel.filter(workflow_kind="script").order_by("-updated_at", "-id")
        if not allow_all:
            query = query.filter(team_id=team_id)
        if keyword.strip():
            query = query.filter(name__icontains=keyword.strip())
        projects: list[dict] = []
        for novel in await query:
            episodes = await self.list_episodes(novel.id)
            available_count = sum(1 for item in episodes if item["available"])
            if available_count:
                projects.append({
                    "id": novel.id,
                    "name": novel.name,
                    "cover": novel.cover,
                    "available_episode_count": available_count,
                })
        total = len(projects)
        start = (page - 1) * page_size
        return {
            "items": projects[start:start + page_size],
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": math.ceil(total / page_size) if total else 0,
            },
        }

    @staticmethod
    async def _current_completed_video(scene: Scene) -> Video | None:
        metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
        workbench = metadata.get("workbench") if isinstance(metadata.get("workbench"), dict) else {}
        raw_current_id = metadata.get("current_video_id") or workbench.get("activeVideoId")
        current_id = raw_current_id if isinstance(raw_current_id, int) else None
        if current_id is not None:
            current = await Video.filter(
                id=current_id,
                scene_id=scene.id,
                status=TaskStatusEnum.completed.value,
            ).first()
            if current is not None and str(current.url or "").strip():
                return current

        # 当前选中版本可能仍在生成或已经失败；历史重制只要求该分镜存在
        # 一个已完成的视频，因此回退到最新的可用完成版本。
        completed = await Video.filter(
            scene_id=scene.id,
            status=TaskStatusEnum.completed.value,
        ).order_by("-id")
        return next(
            (video for video in completed if str(video.url or "").strip()),
            None,
        )

    @staticmethod
    def _video_size(video: Video) -> int:
        metadata = video.metadata if isinstance(video.metadata, dict) else {}
        value = metadata.get("size_bytes")
        if isinstance(value, int) and value > 0:
            return value
        raw_url = str(video.url or "").split("?", 1)[0]
        relative = raw_url.removeprefix("/media/") if raw_url.startswith("/media/") else ""
        if relative:
            media_root = Path(settings.MEDIA_PATH).resolve()
            path = (media_root / relative).resolve()
            if path.is_relative_to(media_root) and path.is_file():
                return path.stat().st_size
        return 0


remake_history_catalog = RemakeHistoryCatalog()
