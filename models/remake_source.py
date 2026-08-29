from __future__ import annotations

from typing import TYPE_CHECKING

from tortoise import fields

from models._base import AbstractBaseModel

if TYPE_CHECKING:
    from models.ai_task import AiTask
    from models.chapter import Chapter
    from models.novel import Novel


class RemakeSource(AbstractBaseModel):
    """重制项目单集的不可变来源视频及审计信息。"""

    novel: fields.ForeignKeyRelation["Novel"] = fields.ForeignKeyField(
        "models.Novel",
        related_name="remake_sources",
        on_delete=fields.CASCADE,
        description="目标重制项目",
    )
    chapter: fields.OneToOneRelation["Chapter"] = fields.OneToOneField(
        "models.Chapter",
        related_name="remake_source",
        on_delete=fields.CASCADE,
        description="目标章节/集",
    )
    episode_number = fields.IntField(description="项目内集数", db_index=True)
    source_kind = fields.CharField(
        max_length=16,
        description="来源类型：upload/history",
    )
    storage_provider = fields.CharField(
        max_length=16,
        description="存储类型：local/oss",
    )
    object_key = fields.CharField(
        max_length=500,
        description="受控媒体 key 或相对路径",
    )
    original_filename = fields.CharField(max_length=255, description="原文件名")
    mime_type = fields.CharField(max_length=120, null=True, description="展示用 MIME")
    size_bytes = fields.BigIntField(description="媒体字节数")
    duration_seconds = fields.FloatField(description="媒体时长（秒）")
    width = fields.IntField(description="视频宽度")
    height = fields.IntField(description="视频高度")
    container_format = fields.CharField(max_length=32, description="真实容器格式")
    checksum = fields.CharField(max_length=64, description="来源文件 SHA-256")
    source_novel_id = fields.IntField(
        null=True,
        description="历史来源项目 ID 审计快照，不设外键",
    )
    source_chapter_id = fields.IntField(
        null=True,
        description="历史来源章节 ID 审计快照，不设外键",
    )
    source_video_manifest = fields.JSONField(
        default=dict,
        description="历史来源组成视频与快照清单",
    )
    media_status = fields.CharField(
        max_length=16,
        default="ready",
        description="ready/processing/completed/failed",
    )
    analysis_task: fields.ForeignKeyNullableRelation["AiTask"] = fields.ForeignKeyField(
        "models.AiTask",
        related_name="remake_sources",
        null=True,
        on_delete=fields.SET_NULL,
        description="当前拆解任务",
    )
    team_id = fields.IntField(null=True, db_index=True, description="所属团队")
    created_by = fields.IntField(null=True, description="创建人")

    class Meta:
        table = "remake_sources"
        table_description = "重制项目不可变来源视频"
        unique_together = (("novel", "episode_number"),)
