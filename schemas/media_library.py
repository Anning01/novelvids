from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas._base import BaseResponse
from services.oss import resolve_media_url


class AudioReferenceOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    gender: str
    audio_url: str
    avatar_url: str
    asset_id: str
    source: str = "system"
    duration: float | None = None
    team_id: int | None = None
    is_active: bool

    @model_validator(mode="after")
    def _resolve_media(self):
        self.audio_url = resolve_media_url(self.audio_url)
        self.avatar_url = resolve_media_url(self.avatar_url)
        return self


class AudioReferenceOssFinalizeIn(BaseModel):
    key: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=255)
    nickname: str = Field(min_length=1, max_length=100)
    gender: str = Field(default="未设置", max_length=32)
    novel_id: int | None = Field(default=None, ge=1)

    @field_validator("nickname")
    @classmethod
    def _validate_nickname(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("音色名称不能为空")
        return stripped

    @field_validator("gender")
    @classmethod
    def _strip_gender(cls, value: str) -> str:
        return value.strip()


class AudioReferenceTrimIn(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    novel_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_range(self):
        duration = self.end - self.start
        if duration < 1:
            raise ValueError("裁剪片段不能少于 1 秒")
        if duration > 30:
            raise ValueError("裁剪片段不能超过 30 秒")
        return self


class DigitalHumanOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    country: str
    age: int = Field(ge=0)
    gender: str
    occupation: str
    asset_id: str
    image_url: str
    is_active: bool

    @model_validator(mode="after")
    def _resolve_media(self):
        self.image_url = resolve_media_url(self.image_url)
        return self
