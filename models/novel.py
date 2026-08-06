from typing import TYPE_CHECKING
from tortoise import fields

from models._base import AbstractBaseModel

if TYPE_CHECKING:
    from models.chapter import Chapter
    from models.asset import Asset


class Novel(AbstractBaseModel):
    """小说/剧本表"""

    name = fields.CharField(
        max_length=255, unique=True, description="小说/剧本名称"
    )
    author = fields.CharField(max_length=255, description="作者", blank=True, null=True)
    cover = fields.CharField(max_length=255, description="封面", blank=True, null=True)
    description = fields.TextField(description="描述", blank=True, null=True)
    content = fields.TextField(description="内容", blank=True, null=True)
    total_chapters = fields.IntField(default=0, description="总章节数")
    tags = fields.JSONField(null=True, description="项目标签")
    story_outline = fields.TextField(blank=True, null=True, description="故事大纲")
    project_type = fields.CharField(
        max_length=120,
        blank=True,
        null=True,
        description="项目设定类型",
    )
    project_setting = fields.TextField(
        blank=True,
        null=True,
        description="项目设定说明",
    )
    storyboard_strategy = fields.CharField(
        max_length=120,
        blank=True,
        null=True,
        description="分镜策略名称",
    )
    storyboard_setting = fields.TextField(
        blank=True,
        null=True,
        description="分镜策略说明",
    )

    chapters: fields.ReverseRelation["Chapter"]
    assets: fields.ReverseRelation["Asset"]

    class Meta:
        table = "novels"
        table_description = "小说/剧本表"

    def __str__(self):
        return self.name
