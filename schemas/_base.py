from datetime import datetime

from pydantic import BaseModel, field_serializer, Field, ConfigDict


class BaseModelWithTime(BaseModel):
    @field_serializer("*", when_used="json")
    def serialize_datetimes(self, v):
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return v


class BaseResponse(BaseModelWithTime):
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    model_config = ConfigDict(from_attributes=True)
