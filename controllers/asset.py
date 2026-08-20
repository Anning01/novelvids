from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Type
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from tortoise.queryset import QuerySet

from controllers.config import ai_model_config_controller, general_config_controller
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from schemas.asset import AssetCreate, AssetImageEditCreate, AssetUpdate
from schemas.asset_variant import AssetVariantCreate, AssetVariantPatch
from services.ai_task_executor import ai_task_executor
from services.image_generation.capabilities import validate_selection
from services.oss import normalize_media_url
from utils.crud import CRUDBase
from utils.decorators import atomic
from utils.enums import AiTaskTypeEnum, ImageSourceEnum, TaskStatusEnum
from utils.page import QueryParams


def _normalize_asset_media(data: dict) -> dict:
    """写库前把资产图片字段中的签名 URL 降级为 OSS key，避免过期 403。"""
    for key in ("main_image", "angle_image_1", "angle_image_2"):
        raw = data.get(key)
        if isinstance(raw, str) and raw:
            data[key] = normalize_media_url(raw) or raw
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        gallery = metadata.get("image_gallery")
        if isinstance(gallery, list):
            metadata["image_gallery"] = [
                normalize_media_url(item) or item
                for item in gallery
                if isinstance(item, str)
            ]
    return data


def _normalize_image_list(images: list[str]) -> list[str]:
    return [normalize_media_url(item) or item for item in images if item]


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _ordered_union(*values: list[Any] | None) -> list[Any]:
    result: list[Any] = []
    for items in values:
        for item in items or []:
            if item not in result:
                result.append(item)
    return result


def _deep_merge(older: Any, newer: Any) -> Any:
    """Recursively merge dictionaries without letting empty new values erase data."""
    if not isinstance(older, dict) or not isinstance(newer, dict):
        return newer if _non_empty(newer) else older
    result = dict(older)
    for key, value in newer.items():
        if key in result:
            result[key] = _deep_merge(result[key], value)
        elif _non_empty(value):
            result[key] = value
    return result


def _asset_rank(asset: Asset) -> tuple[int, float, int]:
    updated_at = asset.updated_at or asset.created_at
    if updated_at is None:
        updated_at = datetime.min.replace(tzinfo=timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (
        int(asset.last_updated_chapter or 0),
        updated_at.timestamp(),
        int(asset.id),
    )


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
        data = _normalize_asset_media(data)
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
        return await super().update(instance, _normalize_asset_media(obj_in.model_dump(exclude_unset=True)))

    async def patch(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().patch(instance, _normalize_asset_media(obj_in.model_dump(exclude_unset=True)))

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

    @atomic()
    async def merge(self, source_asset_id: int, target_asset_id: int) -> dict[str, Any]:
        """Merge source into target, preserving target identity and every useful field."""
        if source_asset_id == target_asset_id:
            raise HTTPException(status_code=400, detail="不能合并同一个资产")

        locked_assets = await Asset.filter(
            id__in=[source_asset_id, target_asset_id]
        ).select_for_update()
        by_id = {asset.id: asset for asset in locked_assets}
        source = by_id.get(source_asset_id)
        target = by_id.get(target_asset_id)
        if source is None or target is None:
            raise HTTPException(status_code=404, detail="待合并资产不存在")
        if source.novel_id != target.novel_id:
            raise HTTPException(status_code=400, detail="只能合并同一项目内的资产")
        if source.asset_type != target.asset_type:
            raise HTTPException(status_code=400, detail="只能合并相同类型的资产")

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.reference_image.value,
            status__in=[
                TaskStatusEnum.pending.value,
                TaskStatusEnum.running.value,
                TaskStatusEnum.queued.value,
            ],
        )
        busy_ids = {
            int(task.request_params.get("asset_id"))
            for task in active_tasks
            if task.request_params.get("asset_id") is not None
        }
        if source.id in busy_ids or target.id in busy_ids:
            raise HTTPException(
                status_code=409,
                detail="资产正在生成参考图，请等待任务完成后再合并",
            )

        newer, older = sorted((source, target), key=_asset_rank, reverse=True)
        final_name = newer.canonical_name or older.canonical_name
        aliases = _ordered_union(
            [source.canonical_name, target.canonical_name],
            source.aliases,
            target.aliases,
        )
        aliases = [value for value in aliases if value and value != final_name]
        source_chapters = sorted({
            int(chapter)
            for chapter in _ordered_union(
                source.source_chapters,
                target.source_chapters,
            )
        })

        image_candidates: list[tuple[str, Asset]] = []
        for asset in (newer, older):
            for image in (
                asset.main_image,
                asset.angle_image_1,
                asset.angle_image_2,
            ):
                if image and all(existing[0] != image for existing in image_candidates):
                    image_candidates.append((image, asset))
        selected_images = image_candidates[:3]
        image_source_asset = selected_images[0][1] if selected_images else None

        merged_metadata = _deep_merge(
            older.metadata if isinstance(older.metadata, dict) else {},
            newer.metadata if isinstance(newer.metadata, dict) else {},
        )
        merge_history = list(merged_metadata.get("merge_history") or [])
        merge_history.append({
            "source_asset_id": source.id,
            "source_name": source.canonical_name,
            "target_asset_id": target.id,
            "target_name": target.canonical_name,
            "data_source_asset_id": newer.id,
            "image_source_asset_id": image_source_asset.id if image_source_asset else None,
            "merged_at": datetime.now(timezone.utc).isoformat(),
        })
        merged_metadata["merge_history"] = merge_history
        extra_images = [image for image, _ in image_candidates[3:]]
        if extra_images:
            merged_metadata["merged_reference_images"] = _ordered_union(
                merged_metadata.get("merged_reference_images"),
                extra_images,
            )

        await source.fetch_related("scenes", "variants")
        await target.fetch_related("scenes", "variants")
        target_scene_ids = {scene.id for scene in target.scenes}
        for scene in source.scenes:
            if scene.id not in target_scene_ids:
                await scene.assets.add(target)

        target_variants = {variant.name: variant for variant in target.variants}
        for source_variant in list(source.variants):
            target_variant = target_variants.get(source_variant.name)
            if target_variant is None:
                source_variant.asset_id = target.id
                await source_variant.save(update_fields=["asset_id", "updated_at"])
                target_variants[source_variant.name] = source_variant
                continue

            variant_newer, variant_older = sorted(
                (source_variant, target_variant),
                key=lambda variant: (
                    variant.updated_at or variant.created_at,
                    variant.id,
                ),
                reverse=True,
            )
            target_variant.description = (
                variant_newer.description or variant_older.description
            )
            target_variant.base_traits = (
                variant_newer.base_traits or variant_older.base_traits
            )
            target_variant.chapter_numbers = sorted({
                int(chapter)
                for chapter in _ordered_union(
                    source_variant.chapter_numbers,
                    target_variant.chapter_numbers,
                )
            })
            target_variant.images = _ordered_union(
                variant_newer.images,
                variant_older.images,
            )
            target_variant.metadata = _deep_merge(
                variant_older.metadata,
                variant_newer.metadata,
            )
            await target_variant.save()
            await source_variant.delete()

        # Delete the source before applying a source canonical name to avoid the
        # project/type/name unique constraint. Scene and variant links are already moved.
        await source.delete()

        target.canonical_name = final_name
        target.aliases = aliases
        target.description = newer.description or older.description
        target.base_traits = newer.base_traits or older.base_traits
        target.main_image = selected_images[0][0] if len(selected_images) > 0 else None
        target.angle_image_1 = selected_images[1][0] if len(selected_images) > 1 else None
        target.angle_image_2 = selected_images[2][0] if len(selected_images) > 2 else None
        target.image_source = (
            image_source_asset.image_source
            if image_source_asset is not None
            else newer.image_source
        )
        target.is_global = bool(source.is_global or target.is_global)
        target.source_chapters = source_chapters
        target.last_updated_chapter = max(
            int(source.last_updated_chapter or 0),
            int(target.last_updated_chapter or 0),
        )
        target.metadata = merged_metadata
        await target.save()
        await target.fetch_related("variants")

        summary = [
            f"资料采用「{newer.canonical_name}」的较新版本",
            f"合并 {len(source_chapters)} 个出现章节",
        ]
        if selected_images:
            summary.append(f"保留 {len(image_candidates)} 张参考图片")
        if target.variants:
            summary.append(f"保留 {len(target.variants)} 个视觉形态")

        return {
            "asset": target,
            "removed_asset_id": source.id,
            "data_source_asset_id": newer.id,
            "image_source_asset_id": (
                image_source_asset.id if image_source_asset else None
            ),
            "summary": summary,
        }

    async def list_variants(self, asset_id: int) -> list[AssetVariant]:
        await self.get(asset_id)
        return await AssetVariant.filter(asset_id=asset_id).order_by("id")

    async def create_variant(self, asset_id: int, obj_in: AssetVariantCreate) -> AssetVariant:
        await self.get(asset_id)
        data = obj_in.model_dump(exclude_unset=True)
        if isinstance(data.get("images"), list):
            data["images"] = _normalize_image_list(data["images"])
        return await AssetVariant.create(asset_id=asset_id, **data)

    async def patch_variant(
        self,
        asset_id: int,
        variant_id: int,
        obj_in: AssetVariantPatch,
    ) -> AssetVariant:
        variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="资产形态不存在")
        data = obj_in.model_dump(exclude_unset=True)
        if isinstance(data.get("images"), list):
            data["images"] = _normalize_image_list(data["images"])
        variant.update_from_dict(data)
        await variant.save()
        return variant

    async def assign_variant_to_chapter(
        self,
        asset_id: int,
        variant_id: int,
        chapter_number: int,
    ) -> list[AssetVariant]:
        """Make exactly one variant of an asset active for a chapter number."""
        await self.get(asset_id)
        variants = await AssetVariant.filter(asset_id=asset_id).order_by("id")
        target = next((variant for variant in variants if variant.id == variant_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="资产形态不存在")

        for variant in variants:
            chapters = {
                int(value)
                for value in (variant.chapter_numbers or [])
                if isinstance(value, int) and value > 0
            }
            if variant.id == variant_id:
                chapters.add(chapter_number)
            else:
                chapters.discard(chapter_number)
            normalized = sorted(chapters)
            if normalized != list(variant.chapter_numbers or []):
                variant.chapter_numbers = normalized
                await variant.save(update_fields=["chapter_numbers", "updated_at"])
        return variants

    async def remove_variant(self, asset_id: int, variant_id: int) -> None:
        variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset_id)
        if variant is None:
            raise HTTPException(status_code=404, detail="资产形态不存在")
        await variant.delete()

    async def generation_history(self, asset_id: int) -> list[dict[str, Any]]:
        """Return sanitized base-asset image-generation history."""
        await self.get(asset_id)
        tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.reference_image.value,
        ).order_by("-created_at")
        records: list[dict[str, Any]] = []
        for task in tasks:
            request_params = task.request_params or {}
            if (
                request_params.get("asset_id") != asset_id
                or request_params.get("variant_id") is not None
            ):
                continue
            response_data = task.response_data or {}
            raw_images = response_data.get("images", [])
            images = (
                [image for image in raw_images if isinstance(image, str)]
                if isinstance(raw_images, list)
                else []
            )
            records.append({
                "id": task.id,
                "status": task.status,
                "images": images,
                "error_message": task.error_message,
                "model": request_params.get("model"),
                "clarity": request_params.get("clarity"),
                "aspect_ratio": request_params.get("aspect_ratio"),
                "output_format": request_params.get("output_format"),
                "created_at": task.created_at,
                "finished_at": task.finished_at,
            })
        return records

    @atomic()
    async def record_image_edit(
        self,
        asset_id: int,
        payload: AssetImageEditCreate,
    ) -> Asset:
        """Store a raster annotation as the current asset image and a restorable history run."""
        asset = await self.get(asset_id)
        now = datetime.now(timezone.utc)
        metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
        image_url = normalize_media_url(payload.image_url) or payload.image_url
        source_image_url = (
            normalize_media_url(payload.source_image_url)
            if payload.source_image_url
            else None
        )
        task = await AiTask.create(
            task_type=AiTaskTypeEnum.reference_image.value,
            status=TaskStatusEnum.completed.value,
            request_params={
                "asset_id": asset.id,
                "variant_id": None,
                "operation": "image_annotation",
                "model": "图片标注编辑",
                "aspect_ratio": metadata.get("aspect_ratio"),
                "clarity": metadata.get("clarity") or metadata.get("resolution"),
                "output_format": payload.output_format,
                "source_image_url": source_image_url,
            },
            response_data={"images": [image_url]},
            started_at=now,
            finished_at=now,
        )
        existing_gallery = metadata.get("image_gallery")
        gallery = existing_gallery if isinstance(existing_gallery, list) else []
        image_gallery = [
            image_url,
            *[
                normalize_media_url(image) or image
                for image in gallery
                if isinstance(image, str) and image != image_url
            ],
        ]
        asset.main_image = image_url
        asset.metadata = {
            **metadata,
            "image_gallery": image_gallery,
            "edited_generation_task_id": str(task.id),
        }
        await asset.save(update_fields=["main_image", "metadata", "updated_at"])
        return asset

    async def restore_generation(self, asset_id: int, task_id: UUID) -> Asset:
        """Restore a completed image-generation result as the asset's current image."""
        asset = await self.get(asset_id)
        task = await AiTask.get_or_none(
            id=task_id,
            task_type=AiTaskTypeEnum.reference_image.value,
        )
        request_params = task.request_params if task else {}
        if (
            task is None
            or request_params.get("asset_id") != asset_id
            or request_params.get("variant_id") is not None
        ):
            raise HTTPException(status_code=404, detail="该生成记录不存在")
        if task.status != TaskStatusEnum.completed.value:
            raise HTTPException(status_code=400, detail="只有生成成功的记录可以设为当前图片")
        response_data = task.response_data or {}
        raw_images = response_data.get("images", [])
        images = (
            [image for image in raw_images if isinstance(image, str) and image]
            if isinstance(raw_images, list)
            else []
        )
        if not images:
            raise HTTPException(status_code=400, detail="该生成记录没有可恢复的图片")

        metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
        asset.main_image = images[0]
        asset.image_source = ImageSourceEnum.ai.value
        asset.metadata = {
            **metadata,
            "image_gallery": images,
            "restored_generation_task_id": str(task.id),
        }
        await asset.save(update_fields=[
            "main_image",
            "image_source",
            "metadata",
            "updated_at",
        ])
        return asset

    async def reference(
        self,
        asset_id: int,
        variant_id: int | None = None,
        team_id: int | None = None,
        user_id: int | None = None,
    ) -> AiTask:
        """提交参考图生成任务。"""
        asset = await self.get(asset_id)
        variant = None
        if variant_id is not None:
            variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset.id)
            if variant is None:
                raise HTTPException(status_code=404, detail="资产形态不存在")

        # 1. 获取任务配置
        metadata = asset.metadata or {}
        variant_metadata = (
            variant.metadata
            if variant and isinstance(variant.metadata, dict)
            else {}
        )
        effective_metadata = {**metadata, **variant_metadata}
        requested_config_id = effective_metadata.get("model_config_id")
        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.reference_image.value,
            int(requested_config_id) if requested_config_id else None,
            team_id=team_id,
        )
        workbench = effective_metadata.get("workbench")
        if not isinstance(workbench, dict):
            workbench = {}
        selection = validate_selection(
            config.image_model_type,
            clarity=(
                effective_metadata.get("clarity")
                or effective_metadata.get("resolution")
                or workbench.get("clarity")
                or workbench.get("resolution")
            ),
            aspect_ratio=(
                effective_metadata.get("aspect_ratio")
                or workbench.get("aspectRatio")
            ),
            output_format=(
                effective_metadata.get("output_format")
                or workbench.get("outputFormat")
                or workbench.get("format")
            ),
            generation_count=(
                effective_metadata.get("generation_count")
                or workbench.get("generationCount")
            ),
        )

        prompt_language = await general_config_controller.get_prompt_language()

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
            "model_config_id": config.id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "api_protocol": config.api_protocol,
            "variant_id": variant.id if variant else None,
            "prompt_language": prompt_language,
            "clarity": selection.clarity,
            "resolution": selection.provider_size,
            "aspect_ratio": selection.aspect_ratio,
            "output_format": selection.output_format,
            "quality": selection.provider_quality,
            "generation_count": selection.generation_count,
        }
        if team_id is not None:
            request_params["team_id"] = team_id
        if user_id is not None:
            request_params["user_id"] = user_id

        task = await ai_task_executor.submit(
            AiTaskTypeEnum.reference_image, request_params
        )
        task.request_params = {
            **(task.request_params or request_params),
            "generation_run_id": str(task.id),
        }
        await task.save(update_fields=["request_params", "updated_at"])
        return task

    async def active_generations(self, novel_id: int) -> list[dict]:
        """返回指定项目内仍在进行中的参考图生成任务（用于刷新后恢复生成中状态）。"""
        tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.reference_image.value,
            status__in=[
                TaskStatusEnum.pending.value,
                TaskStatusEnum.running.value,
                TaskStatusEnum.queued.value,
            ],
        )
        result: list[dict] = []
        for task in tasks:
            params = task.request_params or {}
            if params.get("novel_id") != novel_id:
                continue
            asset_id = params.get("asset_id")
            if asset_id is None:
                continue
            result.append(
                {
                    "asset_id": int(asset_id),
                    "task_id": str(task.id),
                    "status": task.status,
                }
            )
        return result


asset_controller = AssetController()
