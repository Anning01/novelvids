"""一次性回填：把分镜 prompt 中 `@{实体名}` 引用的资产补链到 scene.assets。

背景：早期分镜生成只把实体引用写进 prompt 文本，没有持久化 scene.assets 关联，
导致故事版（文本推断）与画布工作流（只读 scene.assets）展示不一致。此模块按与
生成逻辑一致的 `@{}` 引用判定，把存量镜头的资产关联补齐，实现单一数据源。
"""

import logging

from models.asset import Asset
from models.chapter import Chapter
from models.scene import Scene
from prompts.storyboard import entity_reference_names
from schemas.scene import SceneEntity
from utils.enums import AssetTypeEnum

logger = logging.getLogger(__name__)

REFERENCE_ASSET_TYPES = (
    AssetTypeEnum.person,
    AssetTypeEnum.scene,
    AssetTypeEnum.item,
)


async def backfill_scene_assets() -> dict[str, int]:
    """扫描全部分镜，把 prompt 中 @{} 引用的资产补链到 scene.assets，幂等可重复执行。"""
    stats = {"scenes": 0, "updated_scenes": 0, "linked_assets": 0}
    scenes = await Scene.all()
    chapter_novels = {
        row["id"]: row["novel_id"]
        for row in await Chapter.filter(
            id__in={scene.chapter_id for scene in scenes}
        ).values("id", "novel_id")
    }
    asset_cache: dict[int, list[Asset]] = {}

    async def assets_for_novel(novel_id: int) -> list[Asset]:
        if novel_id not in asset_cache:
            asset_cache[novel_id] = await Asset.filter(
                novel_id=novel_id,
                asset_type__in=[asset_type.value for asset_type in REFERENCE_ASSET_TYPES],
            )
        return asset_cache[novel_id]

    for scene in scenes:
        stats["scenes"] += 1
        novel_id = chapter_novels.get(scene.chapter_id)
        if novel_id is None:
            continue
        text = f"{scene.description or ''}\n{scene.prompt or ''}"
        assets = await assets_for_novel(novel_id)
        entities = [
            SceneEntity(
                name=asset.canonical_name,
                aliases=asset.aliases or [],
                description=asset.description or asset.base_traits or "",
                asset_type=AssetTypeEnum(asset.asset_type).nickname,
                asset_id=asset.id,
            )
            for asset in assets
        ]
        referenced = entity_reference_names(text, entities)
        await scene.fetch_related("assets")
        existing_ids = {asset.id for asset in scene.assets}
        missing = [
            entity.asset_id
            for entity in referenced
            if entity.asset_id is not None and entity.asset_id not in existing_ids
        ]
        if missing:
            await scene.assets.add(*await Asset.filter(id__in=missing))
            stats["updated_scenes"] += 1
            stats["linked_assets"] += len(missing)

    return stats
