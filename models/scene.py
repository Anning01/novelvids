from typing import TYPE_CHECKING
from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import TaskStatusEnum

if TYPE_CHECKING:
    from models.chapter import Chapter
    from models.asset import Asset, ChapterAsset


class Scene(AbstractBaseModel):
    """分镜表，表示单个分镜/镜头。"""

    chapter: fields.ForeignKeyRelation["Chapter"] = fields.ForeignKeyField(
        "models.Chapter",
        related_name="scenes",
        on_delete=fields.CASCADE,
        description="所属章节"
    )
    sequence = fields.IntField(db_index=True, description="镜头序列")
    description = fields.TextField(description="描述")
    speaker: fields.ForeignKeyRelation["Asset"] | None = fields.ForeignKeyField(
        "models.Asset",
        related_name="spoken_scenes",
        on_delete=fields.SET_NULL,
        null=True,
        description="资产"
    )
    prompt = fields.TextField(null=True, description="提示词")
    negative_prompt = fields.TextField(null=True, description="负面提示词")
    duration = fields.FloatField(default=0.0)
    status = fields.IntField(default=TaskStatusEnum.pending.value, db_index=True)
    metadata = fields.JSONField(default=dict, description="元数据")

    chapter_appearances: fields.ReverseRelation["ChapterAsset"]

    class Meta:
        table = "scenes"
        unique_together = (("chapter", "sequence"),)

