from pydantic import ConfigDict, Field, model_validator

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
    is_active: bool

    @model_validator(mode="after")
    def _resolve_media(self):
        self.audio_url = resolve_media_url(self.audio_url)
        self.avatar_url = resolve_media_url(self.avatar_url)
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
