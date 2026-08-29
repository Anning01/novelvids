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
    style_key = fields.CharField(
        max_length=64,
        null=True,
        description="视觉风格 key（prompts/styles.py 注册表）",
    )
    workflow_kind = fields.CharField(
        max_length=32,
        default="script",
        db_index=True,
        description="项目工作流类型：script/remake",
    )
    aspect_ratio = fields.CharField(
        max_length=16,
        null=True,
        description="项目默认画面比例",
    )
    resolution = fields.CharField(
        max_length=32,
        null=True,
        description="项目默认视频清晰度",
    )
    custom_style_prompt = fields.TextField(
        null=True,
        description="自定义视觉风格 Prompt；与 style_key 二选一",
    )
    creation_idempotency_key = fields.CharField(
        max_length=64,
        null=True,
        unique=True,
        description="重制项目创建幂等键",
    )
    creation_payload_hash = fields.CharField(
        max_length=64,
        null=True,
        description="规范化重制创建请求 SHA-256",
    )
    video_model_config_id = fields.IntField(
        null=True,
        description="分镜页面默认视频模型配置 ID",
    )
    narrator_audio_reference_id = fields.IntField(
        null=True,
        description="旁白模式使用的参考音频 ID",
    )
    team_id = fields.IntField(
        null=True,
        db_index=True,
        description="所属团队（AUTH_ENABLED=true 时启用；关闭时恒为 NULL）",
    )
    created_by = fields.IntField(
        null=True,
        description="创建人 User.id（AUTH_ENABLED=true 时启用）",
    )

    chapters: fields.ReverseRelation["Chapter"]
    assets: fields.ReverseRelation["Asset"]

    class Meta:
        table = "novels"
        table_description = "小说/剧本表"

    def __str__(self):
        return self.name
