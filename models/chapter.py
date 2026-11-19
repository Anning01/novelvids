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
    episode_pacing = fields.JSONField(null=True)
    screenplay = fields.TextField(null=True, description="本集导演剧本")

    @property
    def production_text(self) -> str:
        return self.screenplay or self.content or ""

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

    async def save(self, using_db=None, update_fields=None, force_create=False, force_update=False):
        watched = {'name', 'number', 'content', 'screenplay'}
        if update_fields is not None and not watched.intersection(update_fields):
            return await super().save(using_db, update_fields, force_create, force_update)
        from services.creation_objects import project_write
        from services.story_memory.invalidation import chapter_changed
        async with project_write(self.novel_id) as connection:
            before = await Chapter.get_or_none(id=self.id).using_db(connection) if self._saved_in_db else None
            await super().save(connection, update_fields, force_create, force_update)
            after = await Chapter.get(id=self.id).using_db(connection)
            await chapter_changed(before, after)
