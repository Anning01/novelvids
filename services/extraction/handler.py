import asyncio
import logging

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
        """
        chapter_id = request_params["chapter_id"]
        novel_id = request_params["novel_id"]
        base_url = request_params["base_url"]
        api_key = request_params["api_key"]
        model = request_params["model"]
        concurrency = request_params.get("concurrency", 1)

        chapter = await Chapter.get(id=chapter_id)
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        semaphore = asyncio.Semaphore(concurrency)

        async def run_extractor(extractor_cls, asset_type, result_key):
            async with semaphore:
                extractor = extractor_cls(client, model=model)
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
        for item in items:
            # 按 novel + asset_type + canonical_name 查找已有资产
            existing = await Asset.get_or_none(
                novel_id=novel_id,
                asset_type=asset_type.value,
                canonical_name=item.name,
            )

            if existing:
                # 增量更新：合并别名、追加章节、更新描述
                merged_aliases = list(set(existing.aliases + item.aliases))
                source_chapters = existing.source_chapters
                if chapter_number not in source_chapters:
                    source_chapters.append(chapter_number)

                existing.aliases = merged_aliases
                existing.description = item.description
                existing.base_traits = item.base_traits
                existing.source_chapters = source_chapters
                existing.last_updated_chapter = chapter_number
                await existing.save(update_fields=[
                    "aliases", "description", "base_traits",
                    "source_chapters", "last_updated_chapter", "updated_at",
                ])
                saved.append({"name": item.name, "action": "updated"})
            else:
                await Asset.create(
                    novel_id=novel_id,
                    asset_type=asset_type.value,
                    canonical_name=item.name,
                    aliases=item.aliases,
                    description=item.description,
                    base_traits=item.base_traits,
                    source_chapters=[chapter_number],
                    last_updated_chapter=chapter_number,
                )
                saved.append({"name": item.name, "action": "created"})

        return saved
