"""SSH 媒体处理的文件清单；不携带模型或存储凭据。"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MediaWorkerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["create", "prepare", "split", "process", "cleanup"]
    job_id: UUID
    extension: Literal[".mp4", ".mov"] = ".mp4"
    max_bytes: int = Field(default=35_000_000, gt=1024 * 1024, le=500 * 1024 * 1024)


class PreparedMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(pattern=r"^model\.(mp4|mov)$")
    size_bytes: int = Field(gt=0)


class MediaScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(pattern=r"^scene-[0-9]{3,}\.mp4$")
    duration_seconds: float = Field(gt=0, allow_inf_nan=False)


class MediaScenes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: Annotated[list[MediaScene], Field(min_length=1)]
