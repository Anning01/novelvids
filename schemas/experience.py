"""Small-clip requests use configured model IDs and durable project contexts."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from schemas.video import VideoReferenceMedia


class ExperienceGenerateIn(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: UUID
    task_type: Literal['video', 'image'] = 'video'
    mode: Literal['direct', 'agent', 'reference'] = 'agent'
    model_config_id: int = Field(gt=0)
    prompt: str = Field(min_length=1, max_length=4000)
    aspect_ratio: str = Field(min_length=3, max_length=16)
    resolution: str = Field(min_length=1, max_length=32)
    duration: int = Field(default=5, ge=1, le=30)
    reference_binding: Literal['all', 'mentions'] = 'all'
    reference_media: list[VideoReferenceMedia] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def reference_mode(self):
        if self.task_type == 'image' and (self.mode == 'reference' or self.reference_media):
            raise ValueError('参考图模式与参考视频素材仅用于视频片段')
        if self.reference_binding == 'mentions':
            names = [item.mention_name for item in self.reference_media]
            if any(not name for name in names) or len(set(names)) != len(names):
                raise ValueError('参考素材需要互不重复的引用名称')
        return self


class ExperienceQuoteIn(ExperienceGenerateIn):
    """Read-only pricing does not require a creation ID or a completed prompt."""
    request_id: UUID | None = None
    prompt: str = Field(default='', max_length=4000)
