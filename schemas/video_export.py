from pydantic import BaseModel, ConfigDict, Field


class ExportPrepareIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    chapter_id: int = Field(gt=0)
    expected_source_version: str | None = Field(None, pattern=r'^[a-f0-9]{64}$')


class ExportEnhanceIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_config_id: int = Field(gt=0)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    quote_version: str = Field(pattern=r'^[a-f0-9]{64}$')


class ExportTaskOut(BaseModel):
    export_id: int
    task_id: str
    status: int
