"""模型调用计费流水表。"""

from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import TaskStatusEnum


class ModelUsageRecord(AbstractBaseModel):
    """一行 = 一次可计费模型调用；一次任务可能落多条流水。"""

    novel_id = fields.IntField(db_index=True, description="项目归属（Novel.id）")
    task_type = fields.IntField(db_index=True, description="AI 任务类型")
    billing_type = fields.CharField(max_length=16, description="计费维度：text/image/video")
    ai_task_id = fields.UUIDField(null=True, description="关联 AiTask")
    video_id = fields.IntField(null=True, description="关联 Video")
    model_config_id = fields.IntField(null=True, description="模型配置 ID 快照")
    model_name = fields.CharField(max_length=100, null=True, description="配置名快照")
    model = fields.CharField(max_length=200, description="供应商模型 ID 快照")
    model_type = fields.CharField(max_length=40, null=True, description="图片/视频能力类型快照")
    pricing_snapshot = fields.JSONField(null=True, description="调用时刻定价快照")
    usage = fields.JSONField(default=dict, description="用量（token/张数/秒数）")
    cost = fields.DecimalField(max_digits=18, decimal_places=6, default=0, description="成本（元）")
    currency = fields.CharField(max_length=8, default="CNY", description="币种")
    status = fields.IntField(default=TaskStatusEnum.completed.value, description="任务状态")
    duration_seconds = fields.FloatField(null=True, description="请求总时长（秒）")
    team_id = fields.IntField(
        null=True,
        db_index=True,
        description="归属团队（AUTH_ENABLED=true 时启用；历史数据回填）",
    )
    user_id = fields.IntField(
        null=True,
        db_index=True,
        description="触发调用的成员 User.id（历史数据为空）",
    )

    class Meta:
        table = "model_usage_records"
        table_description = "AI 模型调用计费流水表"
