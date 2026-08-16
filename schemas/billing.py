"""账单计费相关 schema。"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
