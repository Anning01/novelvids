from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


class PlatformSettlement(BaseModel):
    status: Literal["pending", "settled", "not_charged", "review"]
    amount: Decimal | None = Field(None, ge=0, max_digits=18, decimal_places=6)
    currency: str = "CNY"

    @field_serializer("amount", when_used="json")
    def serialize_amount(self, value):
        return format(value, ".6f") if value is not None else None


class PlatformReceiptOut(BaseModel):
    id: UUID
    model: str
    status: str
    usage: dict | None
    settlement: PlatformSettlement
    pricing: dict


class PlatformAccountOut(BaseModel):
    balance: Decimal
    currency: str = "CNY"
    recharge_url: str
