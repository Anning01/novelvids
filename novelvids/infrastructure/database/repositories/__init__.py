"""Database repository implementations."""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from tortoise.models import Model
from tortoise.queryset import QuerySet

from novelvids.infrastructure.database.models import (
    AssetModel,
    ChapterAssetModel,
    ChapterModel,
    ComfyUIWorkflowModel,
    NovelModel,
    SceneModel,
    UsageRecordModel,
    UserModel,
    VideoModel,
)

T = TypeVar("T", bound=Model)


class TortoiseRepository(Generic[T]):
    """Base Tortoise ORM repository implementation."""

    model_class: type[T]

    def _get_queryset(self) -> QuerySet[T]:
        return self.model_class.all()

    async def get_by_id(self, entity_id: UUID) -> T | None:
        return await self.model_class.get_or_none(id=entity_id)

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: dict | None = None,
    ) -> list[T]:
        queryset = self._get_queryset()
        if filters:
            queryset = queryset.filter(**filters)
        return await queryset.offset(skip).limit(limit)

    async def create(self, **data: Any) -> T:
        return await self.model_class.create(**data)

    async def update(self, entity_id: UUID, data: dict) -> T | None:
        entity = await self.get_by_id(entity_id)
        if entity:
            await entity.update_from_dict(data).save()
        return entity

    async def delete(self, entity_id: UUID) -> bool:
        deleted = await self.model_class.filter(id=entity_id).delete()
        return deleted > 0

    async def count(self, filters: dict | None = None) -> int:
        queryset = self._get_queryset()
        if filters:
            queryset = queryset.filter(**filters)
        return await queryset.count()


class TortoiseNovelRepository(TortoiseRepository[NovelModel]):
    """Tortoise ORM repository for novels."""

    model_class = NovelModel

    async def get_by_user_id(self, user_id: UUID) -> list[NovelModel]:
        return await self.model_class.filter(user_id=user_id)

    async def get_with_chapters(self, novel_id: UUID) -> NovelModel | None:
        return await self.model_class.get_or_none(id=novel_id).prefetch_related("chapters")


class TortoiseChapterRepository(TortoiseRepository[ChapterModel]):
    """Tortoise ORM repository for chapters."""

    model_class = ChapterModel

    def _get_queryset(self) -> QuerySet[ChapterModel]:
        """Override to add default ordering by chapter number."""
        return self.model_class.all().order_by("number")

    async def get_by_novel_id(self, novel_id: UUID) -> list[ChapterModel]:
        return await self.model_class.filter(novel_id=novel_id).order_by("number")

    async def get_max_number(self, novel_id: UUID) -> int | None:
        """Get the maximum chapter number for a novel."""
        from tortoise.functions import Max

        result = await self.model_class.filter(novel_id=novel_id).annotate(
            max_num=Max("number")
        ).values("max_num")
        if result and result[0]["max_num"] is not None:
            return result[0]["max_num"]
        return None


class TortoiseSceneRepository(TortoiseRepository[SceneModel]):
    """Tortoise ORM repository for scenes."""

    model_class = SceneModel

    async def get_by_chapter_id(self, chapter_id: UUID) -> list[SceneModel]:
        return await self.model_class.filter(chapter_id=chapter_id).order_by("sequence")


class TortoiseVideoRepository(TortoiseRepository[VideoModel]):
    """Tortoise ORM repository for videos."""

    model_class = VideoModel

    async def get_by_novel_id(self, novel_id: UUID) -> list[VideoModel]:
        return await self.model_class.filter(novel_id=novel_id)


class TortoiseUserRepository(TortoiseRepository[UserModel]):
    """Tortoise ORM repository for users."""

    model_class = UserModel

    async def get_by_email(self, email: str) -> UserModel | None:
        return await self.model_class.get_or_none(email=email)

    async def get_by_username(self, username: str) -> UserModel | None:
        return await self.model_class.get_or_none(username=username)


class TortoiseUsageRecordRepository(TortoiseRepository[UsageRecordModel]):
    """Tortoise ORM repository for usage records."""

    model_class = UsageRecordModel

    async def get_by_user_id(
        self,
        user_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[UsageRecordModel]:
        queryset = self.model_class.filter(user_id=user_id)
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        return await queryset.order_by("-created_at")

    async def get_total_cost(
        self,
        user_id: UUID,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> float:
        from tortoise.functions import Sum

        queryset = self.model_class.filter(user_id=user_id)
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        result = await queryset.annotate(total=Sum("total_cost")).values("total")
        return float(result[0]["total"] or 0) if result else 0.0


class TortoiseWorkflowRepository(TortoiseRepository[ComfyUIWorkflowModel]):
    """Tortoise ORM repository for workflows."""

    model_class = ComfyUIWorkflowModel

    async def get_by_category(self, category: str) -> list[ComfyUIWorkflowModel]:
        return await self.model_class.filter(category=category)

    async def get_default(self, category: str) -> ComfyUIWorkflowModel | None:
        return await self.model_class.get_or_none(category=category, is_default=True)


class TortoiseAssetRepository(TortoiseRepository[AssetModel]):
    """Tortoise ORM repository for assets."""

    model_class = AssetModel

    async def get_by_novel_id(
        self, novel_id: UUID, asset_type: str | None = None
    ) -> list[AssetModel]:
        queryset = self.model_class.filter(novel_id=novel_id)
        if asset_type:
            queryset = queryset.filter(asset_type=asset_type)
        return await queryset.order_by("asset_type", "canonical_name")

    async def get_by_name(
        self, novel_id: UUID, canonical_name: str, asset_type: str
    ) -> AssetModel | None:
        return await self.model_class.get_or_none(
            novel_id=novel_id, canonical_name=canonical_name, asset_type=asset_type
        )

    async def find_by_alias(
        self, novel_id: UUID, alias: str, asset_type: str | None = None
    ) -> AssetModel | None:
        """Find asset by alias using JSON contains query."""
        queryset = self.model_class.filter(novel_id=novel_id)
        if asset_type:
            queryset = queryset.filter(asset_type=asset_type)
        # Check canonical_name or aliases
        assets = await queryset
        for asset in assets:
            if asset.canonical_name == alias or alias in asset.aliases:
                return asset
        return None

    async def get_global_assets(
        self, novel_id: UUID, asset_type: str | None = None
    ) -> list[AssetModel]:
        queryset = self.model_class.filter(novel_id=novel_id, is_global=True)
        if asset_type:
            queryset = queryset.filter(asset_type=asset_type)
        return await queryset.order_by("asset_type", "canonical_name")


class TortoiseChapterAssetRepository(TortoiseRepository[ChapterAssetModel]):
    """Tortoise ORM repository for chapter assets."""

    model_class = ChapterAssetModel

    async def get_by_chapter_id(self, chapter_id: UUID) -> list[ChapterAssetModel]:
        return await self.model_class.filter(chapter_id=chapter_id).prefetch_related("asset")

    async def get_by_asset_id(self, asset_id: UUID) -> list[ChapterAssetModel]:
        return await self.model_class.filter(asset_id=asset_id).prefetch_related("chapter")

    async def get_by_chapter_and_asset(
        self, chapter_id: UUID, asset_id: UUID
    ) -> ChapterAssetModel | None:
        return await self.model_class.get_or_none(chapter_id=chapter_id, asset_id=asset_id)
