"""解析 prompt 中的 @资产昵称，查找匹配资产并收集参考图。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from models.asset import Asset
from models.asset_variant import AssetVariant
from services.video.base import image_to_base64
from config import settings

logger = logging.getLogger(__name__)

# 匹配 @{多字名称} 或 @单字名称（兼容旧格式）
MENTION_PATTERN = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")


async def resolve_assets(
    prompt: str,
    novel_id: int,
    chapter_number: int | None = None,
) -> list[dict[str, Any]]:
    """从 prompt 中解析 @mentions，返回 subjects 列表。"""
    mentions = [m1 or m2 for m1, m2 in MENTION_PATTERN.findall(prompt)]
    logger.info("resolve_assets: mentions=%s (prompt[:100]=%r)", mentions, prompt[:100])
    if not mentions:
        return []

    # 查找该小说下的所有资产（一次查询）
    assets = await Asset.filter(novel_id=novel_id).prefetch_related("variants")
    logger.info(
        "resolve_assets: novel_id=%s, total_assets=%d, names=%s",
        novel_id, len(assets), [a.canonical_name for a in assets],
    )

    subjects: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for mention in mentions:
        name, _, variant_name = mention.partition("#")
        matched = _find_asset(name, assets)
        if matched and matched.id not in seen_ids:
            seen_ids.add(matched.id)
            variants = list(matched.variants)
            variant = (
                _find_variant(variant_name, variants)
                if variant_name
                else _find_chapter_variant(chapter_number, variants)
            )
            images = _collect_images(matched, variant)
            logger.info(
                "resolve_assets: matched %r -> asset_id=%s, images=%d (main=%s, a1=%s, a2=%s)",
                mention, matched.id, len(images),
                bool(matched.main_image), bool(matched.angle_image_1), bool(matched.angle_image_2),
            )
            subjects.append({
                "name": (
                    f"{matched.canonical_name}#{variant.name}"
                    if variant and variant_name
                    else matched.canonical_name
                ),
                "variant_name": variant.name if variant else None,
                "images": images,
                "description": (
                    variant.description or variant.base_traits
                    if variant
                    else matched.description or matched.base_traits or ""
                ),
            })
        elif not matched:
            logger.warning("resolve_assets: mention %r not found in assets", mention)

    return subjects


def _find_asset(name: str, assets: list[Asset]) -> Asset | None:
    """在资产列表中按 canonical_name 或 aliases 匹配。"""
    for asset in assets:
        if asset.canonical_name == name:
            return asset
        if name in (asset.aliases or []):
            return asset
    return None


def _find_variant(name: str, variants: list[AssetVariant]) -> AssetVariant | None:
    return next((variant for variant in variants if variant.name == name), None)


def _find_chapter_variant(
    chapter_number: int | None,
    variants: list[AssetVariant],
) -> AssetVariant | None:
    """同章存在多个形态时，以最后创建的形态作为本章覆盖版本。"""
    if chapter_number is None:
        return None
    matching = [
        variant
        for variant in variants
        if chapter_number in (variant.chapter_numbers or [])
    ]
    return max(matching, key=lambda variant: variant.id, default=None)


def _collect_images(asset: Asset, variant: AssetVariant | None = None) -> list[str]:
    """收集资产采用的参考图（URL 直接返回，本地路径转 base64）。

    基础资产默认只传当前主图；只有显式配置 ``selected_image_urls`` 时才传多张。
    视觉形态仍保留自身的多图语义。
    """
    if variant:
        sources = list(variant.images or [])
    else:
        sources = [
            asset.main_image,
            asset.angle_image_1,
            asset.angle_image_2,
        ]
        gallery = (asset.metadata or {}).get("image_gallery")
        if isinstance(gallery, list):
            sources.extend(item for item in gallery if isinstance(item, str))
        selected_value = (asset.metadata or {}).get("selected_image_urls")
        if isinstance(selected_value, list):
            selected_urls = {
                value.strip()
                for value in selected_value
                if isinstance(value, str) and value.strip()
            }
            sources = [source for source in sources if source in selected_urls]
        else:
            sources = [next((source for source in sources if source), None)]
    images: list[str] = []
    seen: set[str] = set()
    for path in sources:
        if not path:
            continue
        if path in seen:
            continue
        seen.add(path)
        try:
            images.append(resolve_image_source(path))
        except FileNotFoundError:
            logger.warning("resolve_assets: image not found: %s", path)
            continue
    return images[:9]


def resolve_image_source(path: str) -> str:
    """远程图片保留 URL，本地与 /media/ 图片转换为 Base64 data URI。"""
    if path.startswith(("http://", "https://", "data:")):
        return path
    if path.startswith("/media/"):
        path = os.path.join(settings.MEDIA_PATH, path[len("/media/"):])
    return image_to_base64(path)
