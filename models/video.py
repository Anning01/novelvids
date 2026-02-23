from typing import TYPE_CHECKING
from tortoise import fields
from models._base import AbstractBaseModel
from utils.enums import TaskStatusEnum

if TYPE_CHECKING:
    from models.scene import Scene



class Video(AbstractBaseModel):
    """视频表，表示单个视频。"""
    scene: fields.ForeignKeyRelation["Scene"] = fields.ForeignKeyField(
        "models.Scene",
        related_name="videos",
        on_delete=fields.CASCADE,
        description="所属分镜"
    )
    model_type = fields.IntField(db_index=True, description="视频模型类型")
    external_task_id = fields.CharField(max_length=255, null=True, description="外部任务ID")
    url = fields.CharField(max_length=500, null=True, description="视频URL")
    metadata = fields.JSONField(default=dict, description="元数据")
    status = fields.IntField(default=TaskStatusEnum.pending.value, db_index=True)

    class Meta:
        table = "videos"
        table_description = "视频表"