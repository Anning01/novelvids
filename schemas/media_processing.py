"""Credential-free protocol for staged media jobs."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MediaProcessSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    program: Literal['ffmpeg', 'ffprobe', 'derivatives']
    arguments: list[str] = Field(default_factory=list, max_length=4096)
    outputs: list[str] = Field(default_factory=list, max_length=64)
    timeout: int = Field(default=1200, ge=1, le=7200)

    @field_validator('outputs')
    @classmethod
    def output_names(cls, values):
        import re
        if any(not re.fullmatch(r'output-[0-9]+\.[a-zA-Z0-9]+', value) for value in values):
            raise ValueError('Outputs must be staged media filenames')
        return values
