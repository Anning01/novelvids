"""Persistable generation preferences; saving preferences never authorizes media."""
from pydantic import BaseModel, ConfigDict, Field
from services.video_enhancement.contract import EnhancementResolution


class AutoEnhancement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_config_id: int = Field(ge=1)
    resolution: EnhancementResolution = '1080p'
    config_version: str | None = Field(None, pattern=r'^[a-f0-9]{64}$')


class ProjectVideoDefaults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_config_id: int | None = Field(None, ge=1)
    resolution: str = Field(min_length=1, max_length=32)
    aspect_ratio: str = Field(min_length=1, max_length=16)
    return_last_frame: bool = False
    auto_enhancement: AutoEnhancement | None = None


class VideoDefaults(ProjectVideoDefaults):
    model_config_id: int = Field(ge=1)


class ApplyVideoDefaults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapter_id: int = Field(ge=1)
    settings: VideoDefaults
    remember: bool = True
