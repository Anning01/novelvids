from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class SheetEditRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    instruction: str = Field(min_length=1, max_length=8000)
    expected_revision: str = Field(min_length=1, max_length=128)
    model_config_id: int | None = Field(None, gt=0)


class SheetRestoreRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: UUID
    source: bool = False
    expected_revision: str = Field(min_length=1, max_length=128)
