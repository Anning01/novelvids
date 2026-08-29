from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from schemas._base import BaseResponse


class RemakeSourceOut(BaseResponse):
    """提交后不可变重制来源。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    chapter_id: int
    episode_number: int = Field(..., ge=1)
    source_kind: Literal["upload", "history"]
    storage_provider: Literal["local", "oss"]
    object_key: str
    original_filename: str
    mime_type: str | None = None
    size_bytes: int = Field(..., gt=0, le=500 * 1024 * 1024)
    duration_seconds: float = Field(..., gt=0, le=1200)
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    container_format: str
    checksum: str
    source_novel_id: int | None = None
    source_chapter_id: int | None = None
    source_video_manifest: dict = Field(default_factory=dict)
    media_status: Literal["ready", "processing", "completed", "failed"]
    analysis_task_id: UUID | None = None
    team_id: int | None = None
    created_by: int | None = None


class RemakeProjectSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    episode_number: int | None = Field(None, ge=1, le=99999)
    upload_token: UUID | None = None
    source_chapter_id: int | None = Field(None, ge=1)


class RemakeProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    source_mode: Literal["single_upload", "folder_upload", "history"]
    aspect_ratio: str = Field(..., min_length=1, max_length=16)
    resolution: str = Field(..., min_length=1, max_length=32)
    style_key: str | None = Field(None, max_length=64)
    custom_style_prompt: str | None = Field(None, max_length=2000)
    idempotency_key: UUID
    sources: list[RemakeProjectSourceIn] = Field(..., min_length=1)
