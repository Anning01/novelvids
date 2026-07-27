from __future__ import annotations

from typing import Any, Optional, Type

from fastapi import HTTPException
from pydantic import BaseModel
from tortoise.queryset import QuerySet

from controllers.config import ai_model_config_controller
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from schemas.asset import AssetCreate, AssetUpdate
from schemas.asset_variant import AssetVariantCreate, AssetVariantPatch
from services.ai_task_executor import ai_task_executor
from utils.crud import CRUDBase
from utils.decorators import atomic
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
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

        # 处理 chapter_id 过滤（Python 端过滤 JSON 数组，兼容 SQLite）
        # 前端传参: /api/asset?chapter_id=3
        if params.filters and "chapter_id" in params.filters:
            try:
                chapter_id = int(params.filters.pop("chapter_id"))
                chapter = await Chapter.get_or_none(id=chapter_id)
                if chapter is None:
                    return await super().list(
                        params,
                        response_model,
                        search_fields,
                        base_query.filter(id__in=[]),
                    )
                all_assets = await self.model.filter(
                    novel_id=chapter.novel_id
                ).values("id", "source_chapters")
                matching_ids = [
                    a["id"] for a in all_assets
                    if chapter.number in (a["source_chapters"] or [])
                ]
                base_query = base_query.filter(id__in=matching_ids)
            except (ValueError, TypeError):
                pass  # 忽略无效的 chapter_id

        effective_search_fields = search_fields or (
            ["canonical_name", "description"]
            if isinstance(params.search, str) and params.search
            else []
        )
        return await super().list(
            params,
            response_model,
            effective_search_fields,
            base_query,
        )

    async def create(self, obj_in: AssetCreate, **kwargs) -> Asset:
        data = obj_in.model_dump(exclude_unset=True)
        chapter_id = data.pop("chapter_id", None)
        if chapter_id is not None:
            chapter = await Chapter.get_or_none(id=chapter_id)
            if chapter is None:
                raise HTTPException(status_code=404, detail="章节不存在")
            if chapter.novel_id != data["novel_id"]:
                raise HTTPException(status_code=400, detail="章节不属于当前项目")
            source_chapters = list(data.get("source_chapters") or [])
            if chapter.number not in source_chapters:
                source_chapters.append(chapter.number)
            data["source_chapters"] = sorted(source_chapters)
            data["last_updated_chapter"] = max(
                int(data.get("last_updated_chapter") or 0),
                chapter.number,
            )
        return await super().create(data, **kwargs)

    async def update(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().update(instance, obj_in)

    async def patch(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().patch(instance, obj_in)

    async def remove(self, asset_id: int) -> None:
        instance = await self.get(asset_id)
        await super().remove(instance)

    async def reuse_in_chapter(self, asset_id: int, chapter_id: int) -> Asset:
        asset = await self.get(asset_id)
        chapter = await Chapter.get_or_none(id=chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节不存在")
        if chapter.novel_id != asset.novel_id:
            raise HTTPException(status_code=400, detail="资产与章节不属于同一项目")
        source_chapters = list(asset.source_chapters or [])
        if chapter.number not in source_chapters:
            source_chapters.append(chapter.number)
            asset.source_chapters = sorted(source_chapters)
            asset.last_updated_chapter = max(
                int(asset.last_updated_chapter or 0),
                chapter.number,
            )
            await asset.save(
                update_fields=[
                    "source_chapters",
                    "last_updated_chapter",
                    "updated_at",
                ]
            )
        await asset.fetch_related("variants")
        return asset

    async def get_with_variants(self, asset_id: int) -> Asset:
        instance = await self.get(asset_id)
        await instance.fetch_related("variants")
        return instance

    async def list_variants(self, asset_id: int) -> list[AssetVariant]:
        await self.get(asset_id)
        return await AssetVariant.filter(asset_id=asset_id).order_by("id")

    async def create_variant(self, asset_id: int, obj_in: AssetVariantCreate) -> AssetVariant:
        await self.get(asset_id)
        return await AssetVariant.create(asset_id=asset_id, **obj_in.model_dump(exclude_unset=True))

    async def patch_variant(
        self,
        asset_id: int,
        variant_id: int,
        obj_in: AssetVariantPatch,
    ) -> AssetVariant:
        variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="资产形态不存在")
        variant.update_from_dict(obj_in.model_dump(exclude_unset=True))
        await variant.save()
        return variant

    async def remove_variant(self, asset_id: int, variant_id: int) -> None:
        variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="资产形态不存在")
        await variant.delete()

    async def reference(self, asset_id: int, variant_id: int | None = None) -> AiTask:
        """提交参考图生成任务。"""
        asset = await self.get(asset_id)
        variant = None
        if variant_id is not None:
            variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset.id)
            if variant is None:
                raise HTTPException(status_code=404, detail="资产形态不存在")

        # 1. 获取任务配置
        metadata = asset.metadata or {}
        requested_config_id = metadata.get("model_config_id")
        if requested_config_id:
            config = await ai_model_config_controller.get(int(requested_config_id))
            if config.task_type != AiTaskTypeEnum.reference_image.value:
                raise HTTPException(status_code=400, detail="所选配置不是生图模型")
        else:
            config = await ai_model_config_controller.get_active(
                AiTaskTypeEnum.reference_image.value
            )

        # 2. 清理超时异常任务
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.reference_image)

        # 3. 检查活跃任务
        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.reference_image.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for t in active_tasks:
            # 检查 request_params 中的 asset_id
            if (
                t.request_params.get("asset_id") == asset_id
                and t.request_params.get("variant_id") == variant_id
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"该资产已有进行中的生成任务（{t.id}）",
                )

        # 4. 提交任务
        request_params = {
            "asset_id": asset.id,
            "novel_id": asset.novel_id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "variant_id": variant.id if variant else None,
        }

        task = await ai_task_executor.submit(
            AiTaskTypeEnum.reference_image, request_params
        )
        return task

asset_controller = AssetController()
