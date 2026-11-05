from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FinishedEpisodeVersion(BaseModel):
    id: int
    revision: int | None
    completed_at: datetime
    duration: float | None
    width: int | None
    height: int | None
    fps: float | None


class FinishedEpisodeItem(BaseModel):
    chapter_id: int
    project_id: int
    project_name: str
    number: int
    title: str
    version: FinishedEpisodeVersion
    published_id: int | None
    featured: bool
    can_publish: bool
    can_feature: bool


class FinishedPublicationIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    export_id: int | None = Field(gt=0)
    expected_id: int | None = Field(None, gt=0)


class FinishedFeatureIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    export_id: int = Field(gt=0)
    featured: bool
