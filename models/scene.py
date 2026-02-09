from typing import TYPE_CHECKING
from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import TaskStatusEnum

if TYPE_CHECKING:
    from models.chapter import Chapter
    from models.asset import Asset


class Scene(AbstractBaseModel):
    """分镜表，表示单个分镜/镜头。"""

    chapter: fields.ForeignKeyRelation["Chapter"] = fields.ForeignKeyField(
        "models.Chapter",
        related_name="scenes",
        on_delete=fields.CASCADE,
        description="所属章节"
    )
    sequence = fields.IntField(db_index=True, description="镜头序列")
    description = fields.TextField(null=True, description="描述")
    assets: fields.ManyToManyRelation["Asset"] = fields.ManyToManyField(
        "models.Asset",
        related_name="scenes",
        through="scene_assets",  # 显式指定中间表名
        description="该镜头中涉及的所有资产/角色"
    )
    prompt = fields.JSONField(default=dict, description="提示词")
    duration = fields.FloatField(default=0.0)
    status = fields.IntField(default=TaskStatusEnum.pending.value, db_index=True)
    metadata = fields.JSONField(default=dict, description="元数据")


    class Meta:
        table = "scenes"
        unique_together = (("chapter", "sequence"),)

