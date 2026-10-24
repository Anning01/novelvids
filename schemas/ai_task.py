from datetime import datetime
from typing import Optional, Literal
from uuid import UUID

from pydantic import BaseModel, field_serializer, Field, ConfigDict

from schemas._base import BaseResponse
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class AiTaskOut(BaseResponse):
    """任务查询输出。"""

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("request_params")
    def public_request_params(self, value):
        return {
            key: item
            for key, item in value.items()
            if key
            not in {
                "api_key",
                "base_url",
                "skill_snapshot",
                "agent_configuration",
                "replace_versions",
                "replaced_scene_snapshots",
            }
        }

    id: UUID = Field(..., description="任务ID")
    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    status: int = Field(..., description=TaskStatusEnum.__doc__)
    request_params: dict = Field(default_factory=dict, description="请求参数")
    response_data: Optional[dict] = Field(None, description="返回数据")
    error_message: Optional[str] = Field(None, description="错误消息")
    stage: Optional[str] = Field(None, description="任务当前业务阶段", max_length=32)
    progress: int = Field(0, description="任务进度", ge=0, le=100)
    started_at: Optional[datetime] = Field(None, description="开始执行时间")
    finished_at: Optional[datetime] = Field(None, description="执行完成时间")


class TaskReviewResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    outcome: Literal["not_submitted", "provider_failed", "completed_unrecoverable"]
    note: str = Field(min_length=10, max_length=2000)
