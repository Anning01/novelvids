from __future__ import annotations  # 关键：支持延迟类型求值

from typing import TYPE_CHECKING

from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import TaskStatusEnum, WorkflowStatus

if TYPE_CHECKING:
    from models.novel import Novel
    from models.scene import Scene


class Chapter(AbstractBaseModel):
    """章节表"""

    novel: fields.ForeignKeyRelation["Novel"] = fields.ForeignKeyField(
        "models.Novel",
        related_name="chapters",
        description="所属小说/剧本",
        on_delete=fields.CASCADE,
    )
    number = fields.IntField(
        description="章节序号", db_index=True
    )
    name = fields.CharField(
        max_length=255, description="章节名称"
    )
    content = fields.TextField(description="章节内容")
    status = fields.IntField(
        description="章节状态",
        default=TaskStatusEnum.pending.value,
    )
    workflow_status = fields.IntField(
        description="工作流状态",
        default=WorkflowStatus.draft.value,
    )
    scenes: fields.ReverseRelation["Scene"]

    class Meta:
        table = "chapters"
        table_description = "章节表"

    def __str__(self):
        return self.name
