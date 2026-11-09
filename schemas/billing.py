"""账单计费相关 schema。"""

from datetime import date
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas._base import BaseResponse


class ModelUsageRecordOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    task_type: int
    billing_type: str
    ai_task_id: Optional[UUID] = None
    video_id: Optional[int] = None
    model_config_id: Optional[int] = None
    model_name: Optional[str] = None
    model: str
    model_type: Optional[str] = None
    pricing_snapshot: Optional[dict] = None
    usage: dict
    cost: float
    currency: str
    status: int
    duration_seconds: Optional[float] = None
    cost_source: str = "balance"
    team_id: Optional[int] = None
    user_id: Optional[int] = None
    record_kind: Literal['call', 'agent_conversation'] = 'call'
    conversation_id: Optional[int] = None
    record_count: int = 1
    turn_count: int = 1
    statuses: list[int] = Field(default_factory=list)


class BillingSummaryOut(BaseModel):
    total_cost: float
    total_records: int
    by_billing_type: list[dict]
    by_task_type: list[dict]
    by_model: list[dict]
    daily_trend: list[dict]


class BillingProjectOut(BaseModel):
    novel_id: int
    novel_name: str
    total_cost: float
    record_count: int


class BillingProjectDetailOut(BaseModel):
    novel_id: int
    novel_name: str
    total_cost: float
    record_count: int
    by_task_type: list[dict]


class StatementFilters(BaseModel):
    team_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    snapshot_id: int | None = Field(None, ge=0)

    @model_validator(mode='after')
    def validate_dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError('start_date must not be after end_date')
        if self.end_date == date.max:
            raise ValueError('end_date is out of range')
        return self


class StatementPartyOut(BaseModel):
    id: int
    name: str


class StatementQuery(StatementFilters):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


class StatementPartiesOut(BaseModel):
    teams: list[StatementPartyOut]
    users: list[StatementPartyOut]


class StatementRowOut(BaseModel):
    id: int
    created_at: str
    team_id: int
    team_name: str
    user_id: int | None
    user_name: str | None
    novel_id: int | None
    novel_name: str | None
    usage_record_id: int | None
    billing_type: str | None
    task_type: int | None
    task_status: int | None
    video_id: int | None
    usage: dict
    cost: str
    balance_after: str


class StatementSummaryOut(BaseModel):
    total_cost: str
    total_transactions: int
    team_balance: str | None


class StatementOut(BaseModel):
    items: list[StatementRowOut]
    pagination: dict[str, int]
    summary: StatementSummaryOut
    snapshot_id: int
