from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import Field, ConfigDict

from schemas._base import BaseResponse
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class AiTaskOut(BaseResponse):
    """任务查询输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="任务ID")
    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    status: int = Field(..., description=TaskStatusEnum.__doc__)
    request_params: dict = Field(default_factory=dict, description="请求参数")
    response_data: Optional[dict] = Field(None, description="返回数据")
    error_message: Optional[str] = Field(None, description="错误消息")
    started_at: Optional[datetime] = Field(None, description="开始执行时间")
    finished_at: Optional[datetime] = Field(None, description="执行完成时间")
