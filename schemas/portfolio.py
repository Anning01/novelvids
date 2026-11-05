from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from schemas.finished_episode import FinishedEpisodeVersion

WorkStatus = Literal['private', 'pending', 'public', 'withdrawn']
WorkFilter = Literal['all', 'pending', 'public', 'private', 'featured']
WorkSort = Literal['recent', 'title', 'duration', 'recommended']
ShortTag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class WorkProfile(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default='', max_length=5000)
    category: str = Field(default='', max_length=80)
    tags: list[ShortTag] = Field(default_factory=list, max_length=12)
    cover_chapter_id: int | None = Field(None, gt=0)
    revision: int = Field(ge=0)


class WorkAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['submit', 'approve', 'publish', 'withdraw', 'recommend']
    revision: int = Field(ge=0)
    export_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=500)
    featured: bool = False
    featured_order: int = Field(0, ge=0, le=9999)


class WorkEpisode(BaseModel):
    chapter_id: int
    number: int
    title: str
    version: FinishedEpisodeVersion
    published_id: int | None = None


class WorkSummary(BaseModel):
    project_id: int
    title: str
    category: str
    tags: list[str]
    status: WorkStatus
    featured: bool
    featured_order: int
    episode_count: int
    duration: float | None
    resolution: str
    cover_export_id: int
    producer: str = ''
    producer_id: int | None = None
    production_seconds: int | None = None
    recorded_cost: float | None = None
    cost_scope: Literal['project', 'self'] | None = None
    archived_at: datetime
    updated_at: datetime
    last_action: str


class WorkDetail(WorkSummary):
    description: str
    cover_chapter_id: int | None
    revision: int
    episodes: list[WorkEpisode]
    can_edit: bool = False
    can_manage: bool = False
