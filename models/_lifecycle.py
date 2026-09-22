"""Active-object queries shared by the workbench and the creation assistant."""

from tortoise import fields
from tortoise.manager import Manager
from tortoise.queryset import QuerySet

from models._base import AbstractBaseModel


class ActiveObjects(Manager):
    def get_queryset(self) -> QuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class RecoverableModel(AbstractBaseModel):
    deleted_at = fields.DatetimeField(null=True, description="可恢复删除时间")

    @classmethod
    def with_deleted(cls) -> QuerySet:
        """Internal history/recovery access; callers must still scope by project."""
        return QuerySet(cls)

    async def save(self, using_db=None, update_fields=None, force_create=False, force_update=False):
        from models.chapter import Chapter
        from models.asset import Asset
        from services.creation_objects import project_write

        novel_id = getattr(self, 'novel_id', None)
        if self._meta.db_table == 'scenes':
            chapter = await Chapter.get_or_none(id=self.chapter_id)
            novel_id = chapter.novel_id if chapter else None
        elif self._meta.db_table == 'asset_variants':
            asset = await Asset.get_or_none(id=self.asset_id)
            novel_id = asset.novel_id if asset else None
        if novel_id is None:
            raise ValueError('所属章节或设定不存在，不能保存')
        async with project_write(novel_id) as connection:
            if self._meta.db_table == 'asset_variants' and not await Asset.filter(id=self.asset_id).exists():
                raise ValueError('所属设定已被移除，不能保存形态')
            # Model.create() resolves its default client before calling save().
            # Once inside the transaction, that original SQLite client owns the
            # outer lock; reusing it here would wait on our own transaction.
            await self._save_active(connection, update_fields, force_create, force_update)

    async def _save_active(self, using_db, update_fields, force_create, force_update):
        if self._saved_in_db and not force_create:
            if not await type(self).filter(id=self.pk).using_db(using_db).exists():
                raise ValueError("对象已被移除，不能保存迟到的更新")
            # Lifecycle state is changed only by the transactional lifecycle
            # service. A previously loaded model must never clear deleted_at.
            update_fields = list(update_fields) if update_fields is not None else [
                name for name in self._meta.db_fields if name not in {'id', 'deleted_at', 'created_at'}
            ]
            if 'deleted_at' in update_fields:
                raise ValueError("删除状态必须通过恢复服务修改")
            if not update_fields:
                return
        await super().save(using_db=using_db, update_fields=update_fields,
                           force_create=force_create, force_update=force_update)

    class Meta:
        abstract = True
