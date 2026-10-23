from typing import Literal

from pydantic import BaseModel, Field, field_validator
from utils.media_name import video_display_name


class FolderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("文件夹名称无效")
        return value


class ResourceRename(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空")
        return video_display_name(value)


class ResourceUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    folder_id: int = Field(default=0, ge=0)


class ResourceIds(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value):
            raise ValueError("资源 ID 无效")
        return list(dict.fromkeys(value))


class ResourceMove(ResourceIds):
    folder_id: int = Field(default=0, ge=0)


class ResourceImport(BaseModel):
    source: Literal["video", "scene", "upload"]
    source_id: int = Field(ge=1)
    media_url: str | None = Field(default=None, max_length=2000)
    node_key: str | None = Field(default=None, max_length=255)
    folder_id: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=255)


class ResourceSelection(ResourceIds):
    model_config_id: int = Field(ge=1)
