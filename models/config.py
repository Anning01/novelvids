from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import AiTaskTypeEnum


class AiModelConfig(AbstractBaseModel):
    """AI 模型配置表 - 每种任务类型可配置多个，启用仅一个。"""

    task_type = fields.IntField(
        db_index=True,
        description="主任务类型（兼容旧数据）",
    )
    task_types = fields.JSONField(
        default=list,
        description="模型支持的任务类型列表",
    )
    name = fields.CharField(
        max_length=100,
        description="配置名称，如 deepseek-v3、gpt-4o",
    )
    base_url = fields.CharField(
        max_length=500,
        description="API 地址",
    )
    api_key = fields.CharField(
        max_length=500,
        description="API Key",
    )
    model = fields.CharField(
        max_length=200,
        description="模型名称",
    )
    is_active = fields.BooleanField(
        default=False,
        db_index=True,
        description="是否启用",
    )
    concurrency = fields.IntField(
        default=1,
        description="并发数",
    )
    supports_json_output = fields.BooleanField(
        default=False,
        description="是否支持 response_format=json_object",
    )

    class Meta:
        table = "ai_model_configs"
        table_description = "AI 模型配置表"
        unique_together = (("task_type", "name"),)

    def __str__(self):
        status = "✓" if self.is_active else "✗"
        return f"[{status}] {self.name}({AiTaskTypeEnum(self.task_type).nickname})"
