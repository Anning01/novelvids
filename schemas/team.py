"""团队余额与成员/团队管理 API 的请求/响应模型。"""

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from schemas._base import BaseResponse


def _serialize_decimal(value: Decimal) -> str:
    """Decimal 统一以定点字符串序列化（避免 1E+2 科学计数法）。"""
    return format(value, "f")


class TeamBalanceOut(BaseModel):
    team_id: int = Field(..., description="团队 ID")
    balance: Decimal = Field(..., description="当前余额（元）")

    @field_serializer("balance", when_used="json")
    def _ser_balance(self, value: Decimal) -> str:
        return _serialize_decimal(value)


class BalanceTopUpIn(BaseModel):
    team_id: int = Field(..., gt=0, description="目标团队")
    amount: Decimal = Field(..., gt=0, description="充值金额（元）")
    note: str = Field("", max_length=255, description="备注")


class BalanceTransactionOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    team_id: int
    change_amount: Decimal
    balance_after: Decimal
    type: str
    usage_record_id: int | None = None
    operator_user_id: int | None = None
    note: str = ""

    @field_serializer("change_amount", "balance_after", when_used="json")
    def _ser_amounts(self, value: Decimal) -> str:
        return _serialize_decimal(value)


# ---- 团队成员管理 ----


class MemberPatchIn(BaseModel):
    role: Optional[Literal["admin", "creator", "viewer"]] = Field(None, description="新角色")
    status: Optional[Literal[0, 1]] = Field(None, description="成员状态：0 禁用 / 1 正常")


class MemberResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=200, description="新密码（至少 8 位）")


class MemberLimitIn(BaseModel):
    cost_limit: Optional[Decimal] = Field(
        None, ge=0, description="个人累计消费限额（元）；null 表示不限"
    )


class MemberOut(BaseModel):
    user_id: int = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    nickname: str = Field("", description="昵称")
    role: str = Field(..., description="团队角色")
    status: int = Field(1, description="成员状态：0 禁用 / 1 正常")
    total_cost: Decimal = Field(Decimal("0"), description="累计历史消耗金额（元）")
    cost_limit: Optional[Decimal] = Field(None, description="个人累计消费限额")

    @field_serializer("total_cost", "cost_limit", when_used="json")
    def _ser_costs(self, value):
        if value is None:
            return None
        return _serialize_decimal(value)


class InviteOut(BaseModel):
    token: str = Field(..., description="邀请令牌")
    team_id: int = Field(..., description="团队 ID")
    team_name: str = Field("", description="团队名称")
    role: str = Field(..., description="加入后的角色")
    expires_at: str = Field("", description="过期时间")


# ---- 团队管理（超管） ----


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    balance: Decimal = Decimal("0")
    model_config_source: str = "official"
    status: int = 1
    member_limit: Optional[int] = Field(None, description="成员人数上限；null 不限")
    owner_user_id: Optional[int] = Field(None, description="团队所有人 User.id")
    owner_username: str = Field("", description="团队所有人用户名")
    member_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    @field_serializer("balance", when_used="json")
    def _ser_balance(self, value: Decimal) -> str:
        return _serialize_decimal(value)


class TeamCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="团队名称")
    owner_user_id: int = Field(..., gt=0, description="团队所有人（自动成为团队管理员）")
    member_limit: Optional[int] = Field(None, ge=1, description="成员人数上限；null 不限")


class TeamPatchIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="团队名称")
    status: Optional[int] = Field(None, description="团队状态：0 停用 / 1 正常")
    member_limit: Optional[int] = Field(None, ge=1, description="成员人数上限；null 不限")
