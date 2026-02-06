from typing import Any, Optional, Type

from pydantic import BaseModel
from tortoise.queryset import QuerySet

from models.asset import Asset
from schemas.asset import AssetCreate, AssetUpdate
from utils.crud import CRUDBase
from utils.decorators import atomic
from utils.page import QueryParams


class AssetController(CRUDBase[Asset, AssetCreate, AssetUpdate]):
    def __init__(self):
        super().__init__(model=Asset)

    async def list(
        self,
        params: "QueryParams",
        response_model: Type[BaseModel],
        search_fields: Optional[list[str]] = None,
        base_query: Optional["QuerySet"] = None,
    ) -> dict[str, dict[str, int | Any] | Any]:
        """
        重写 list 方法，支持通过 chapter_id 过滤 JSON 数组。
        """
        if base_query is None:
            base_query = self.model.all()

        # 处理 chapter_id 过滤
        # 前端传参: /api/asset?chapter_id=3
        if params.filters and "chapter_id" in params.filters:
            try:
                chapter_id = int(params.filters.pop("chapter_id"))
                # JSON 数组包含查询：source_chapters 包含 chapter_id
                # 注意：这在 SQLite/PostgreSQL 中通常有效，底层会被转为 JSON_CONTAINS 或类似逻辑
                base_query = base_query.filter(source_chapters__contains=chapter_id)
            except (ValueError, TypeError):
                pass  # 忽略无效的 chapter_id

        return await super().list(params, response_model, search_fields, base_query)
        
    async def update(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().update(instance, obj_in)

    async def patch(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().patch(instance, obj_in)

    async def remove(self, asset_id: int) -> None:
        instance = await self.get(asset_id)
        await super().remove(instance)


asset_controller = AssetController()
