from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class AiTask(AbstractBaseModel):
    """AI 任务表 - 统一管理所有第三方 AI 请求任务。"""

    id = fields.UUIDField(primary_key=True, description="任务ID")
    task_type = fields.IntField(
        db_index=True,
        description="任务类型",
    )
    status = fields.IntField(
        default=TaskStatusEnum.pending.value,
        db_index=True,
        description="任务状态",
    )
    request_params = fields.JSONField(
        default=dict,
        description="请求参数",
    )
    response_data = fields.JSONField(
        null=True,
        description="返回数据",
    )
    error_message = fields.TextField(
        null=True,
        description="错误消息",
    )
    started_at = fields.DatetimeField(
        null=True,
        description="开始执行时间",
    )
    finished_at = fields.DatetimeField(
        null=True,
        description="执行完成时间",
    )

    class Meta:
        table = "ai_tasks"
        table_description = "AI 任务表"