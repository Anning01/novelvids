from pydantic import ConfigDict, Field

from schemas._base import BaseResponse


class AudioReferenceOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    gender: str
    audio_url: str
    avatar_url: str
    asset_id: str
    is_active: bool


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
