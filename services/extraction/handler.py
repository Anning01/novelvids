import asyncio
import logging
import re

from openai import AsyncOpenAI

from models.asset import Asset
from models.chapter import Chapter
from services.ai_task_executor import BaseTaskHandler
from services.extraction.extractor import (
    ItemExtractor,
    PersonExtractor,
    SceneExtractor,
)
from utils.enums import AssetTypeEnum

logger = logging.getLogger(__name__)

# 提取器类型与 AssetTypeEnum 的映射
EXTRACTOR_ASSET_MAP = [
    (PersonExtractor, AssetTypeEnum.person, "persons"),
    (SceneExtractor, AssetTypeEnum.scene, "scenes"),
    (ItemExtractor, AssetTypeEnum.item, "items"),
]


def _identity_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", (value or "").casefold())


def _identity_keys(asset: Asset) -> set[str]:
    return {
        key
        for key in (
            _identity_key(asset.canonical_name),
            *(_identity_key(alias) for alias in (asset.aliases or [])),
        )
        if key
    }


def _ordered_strings(*groups: list[str] | None) -> list[str]:
    result: list[str] = []
    for values in groups:
        for value in values or []:
            value = value.strip()
            if value and value not in result:
                result.append(value)
    return result


class ExtractionTaskHandler(BaseTaskHandler):
    """提取任务处理器 - 人物/场景/物品提取并写入资产表。"""

    async def execute(self, request_params: dict) -> dict:
        """
        request_params:
            chapter_id: int
            novel_id: int
            base_url: str
            api_key: str
            model: str
            concurrency: int
            supports_json_output: bool
        """
        chapter_id = request_params["chapter_id"]
        novel_id = request_params["novel_id"]
        base_url = request_params["base_url"]
        api_key = request_params["api_key"]
        model = request_params["model"]
        concurrency = request_params.get("concurrency", 1)
        supports_json_output = request_params.get("supports_json_output", False)
        prompt_language = request_params.get("prompt_language", "en")

        chapter = await Chapter.get(id=chapter_id)
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        semaphore = asyncio.Semaphore(concurrency)

        async def run_extractor(extractor_cls, asset_type, result_key):
            async with semaphore:
                extractor = extractor_cls(
                    client,
                    model=model,
                    supports_json_output=supports_json_output,
                    prompt_language=prompt_language,
                )
                result = await extractor.extract(chapter.content, chapter.number)
                return asset_type, result_key, result

        # 并发提取（受 semaphore 控制）
        tasks = [
            run_extractor(cls, asset_type, key)
            for cls, asset_type, key in EXTRACTOR_ASSET_MAP
        ]
        results = await asyncio.gather(*tasks)

        # 写入资产表
        summary = {}
        for asset_type, result_key, result in results:
            items = getattr(result, result_key, [])
            saved = await self._save_assets(
                novel_id, chapter.number, asset_type, items
            )
            summary[result_key] = saved

        return summary

    async def _save_assets(
        self,
        novel_id: int,
        chapter_number: int,
        asset_type: AssetTypeEnum,
        items: list,
    ) -> list[dict]:
        """保存/更新资产，增量式合并。"""
        saved = []
        existing_assets = await Asset.filter(
            novel_id=novel_id,
            asset_type=asset_type.value,
        )
        for item in items:
            item_metadata = {}
            if asset_type == AssetTypeEnum.person:
                item_metadata["reference_layout"] = getattr(
                    item,
                    "reference_layout",
                    "character_turnaround",
                )

            incoming_keys = {
                key
                for key in (
                    _identity_key(item.name),
                    *(_identity_key(alias) for alias in item.aliases),
                )
                if key
            }
            # Canonical names and known aliases share one identity space. This
            # keeps later chapters from creating a duplicate just because the
            # novel switches to a nickname.
            existing = next(
                (
                    asset
                    for asset in existing_assets
                    if incoming_keys & _identity_keys(asset)
                ),
                None,
            )

            if existing:
                # Incremental update: newer non-empty semantic data wins, while
                # images and other fields already on the asset remain intact.
                # Re-extracting an earlier chapter must never roll a later
                # state backwards.
                existing_last_chapter = int(existing.last_updated_chapter or 0)
                incoming_is_current = chapter_number >= existing_last_chapter
                merged_aliases = _ordered_strings(
                    existing.aliases,
                    [item.name] if item.name != existing.canonical_name else [],
                    item.aliases,
                )
                source_chapters = list(existing.source_chapters or [])
                if chapter_number not in source_chapters:
                    source_chapters.append(chapter_number)

                existing.aliases = merged_aliases
                if incoming_is_current and item.description.strip():
                    existing.description = item.description
                if incoming_is_current and item.base_traits.strip():
                    existing.base_traits = item.base_traits
                existing_metadata = (
                    dict(existing.metadata)
                    if isinstance(existing.metadata, dict)
                    else {}
                )
                existing.metadata = {**existing_metadata, **item_metadata}
                existing.source_chapters = sorted(source_chapters)
                existing.last_updated_chapter = max(
                    existing_last_chapter,
                    chapter_number,
                )
                await existing.save(update_fields=[
                    "aliases", "description", "base_traits", "metadata",
                    "source_chapters", "last_updated_chapter", "updated_at",
                ])
                saved.append({"name": item.name, "action": "updated"})
            else:
                created = await Asset.create(
                    novel_id=novel_id,
                    asset_type=asset_type.value,
                    canonical_name=item.name,
                    aliases=item.aliases,
                    description=item.description,
                    base_traits=item.base_traits,
                    metadata=item_metadata,
                    source_chapters=[chapter_number],
                    last_updated_chapter=chapter_number,
                )
                existing_assets.append(created)
                saved.append({"name": item.name, "action": "created"})

        return saved
