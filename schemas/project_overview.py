"""Read-only project dashboard; counts describe current, non-archived work."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from schemas._base import BaseModelWithTime
from schemas.novel import NovelBriefOut


class ProjectProduction(BaseModelWithTime):
    chapter_count: int = 0
    storyboard_chapter_count: int = 0
    completed_episode_count: int = 0
    completed_shot_count: int = 0
    shot_count: int = 0
    asset_count: int = 0
    video_seconds: float = 0
    unknown_duration_count: int = 0
    latest_episode_number: int | None = None
    latest_activity_at: datetime
    state: Literal["not_started", "in_progress", "ready"] = "not_started"


class ProjectOverviewItem(NovelBriefOut):
    tags: list[str] = Field(default_factory=list)
    project_type: str | None = None
    production: ProjectProduction


class ProjectOverviewSummary(BaseModel):
    project_count: int = 0
    chapter_count: int = 0
    asset_count: int = 0
    video_seconds: float = 0
    unknown_duration_count: int = 0


class ProjectOverview(BaseModel):
    items: list[ProjectOverviewItem]
    summary: ProjectOverviewSummary
