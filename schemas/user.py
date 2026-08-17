"""用户管理 API 的请求/响应模型。"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from config import settings


def _serialize_datetime(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.strftime(settings.DATETIME_FORMAT)


def _serialize_money(value: Decimal | float | str | None) -> float:
    try:
        return round(float(value or 0), 6)
    except (TypeError, ValueError):
        return 0.0


class UserCreateIn(BaseModel):
    username: str = Field(min_length=1, max_length=100, description="登录用户名")
    password: str = Field(min_length=8, max_length=200, description="初始密码（至少 8 位）")
    nickname: str = Field("", max_length=100, description="昵称")


class UserPatchIn(BaseModel):
    status: Literal[0, 1] = Field(..., description="登录状态：0 禁用 / 1 正常")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str = ""
    is_super_admin: bool = False
    status: int = 1
    created_at: datetime | str | None = ""
    total_cost: Decimal | float | str | None = 0.0
    team_count: int = 0

    @field_serializer("created_at", when_used="json")
    def _ser_created_at(self, value):
        return _serialize_datetime(value)

    @field_serializer("total_cost", when_used="json")
    def _ser_total_cost(self, value):
        return _serialize_money(value)


class UserStatsOut(BaseModel):
    user_count: int = 0
    user_total_cost: float = 0.0
    team_count: int = 0
    team_balance_total: float = 0.0
