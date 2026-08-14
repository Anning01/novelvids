"""解析 prompt 中的 @资产昵称，查找匹配资产并收集参考图。"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any

from models.asset import Asset
from models.asset_variant import AssetVariant
from services.video.base import image_to_base64
from config import settings

logger = logging.getLogger(__name__)

# 匹配 @{多字名称} 或 @单字名称（兼容旧格式）
MENTION_PATTERN = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")


def normalize_selected_variant_ids(value: Any) -> dict[int, int | None]:
    """将 Scene.metadata 中的 JSON 键安全转换为资产与形态 ID。"""
    if not isinstance(value, dict):
        return {}
    selections: dict[int, int | None] = {}
    for raw_asset_id, raw_variant_id in value.items():
        try:
            asset_id = int(raw_asset_id)
            variant_id = int(raw_variant_id) if raw_variant_id is not None else None
        except (TypeError, ValueError):
            continue
        if asset_id < 1 or (variant_id is not None and variant_id < 1):
            continue
        selections[asset_id] = variant_id
    return selections


async def resolve_assets(
    prompt: str,
    novel_id: int,
    chapter_number: int | None = None,
    selected_asset_ids: Sequence[int] | None = None,
    selected_variant_ids: Mapping[int, int | None] | None = None,
) -> list[dict[str, Any]]:
    """解析分镜使用的资产及形态，返回视频模型 subjects。

    只有同时满足“已绑定到分镜”和“在 prompt 中显式引用”的资产才会提交；
    用户在分镜中显式选择的形态优先于 prompt 的 ``#形态`` 与章节默认形态。
    """
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

    allowed_asset_ids = set(selected_asset_ids) if selected_asset_ids is not None else None
    requested_assets: list[tuple[Asset, str]] = []
    seen_ids: set[int] = set()

    for mention in mentions:
        name, _, variant_name = mention.partition("#")
        matched = _find_asset(name, assets)
        if matched and allowed_asset_ids is not None and matched.id not in allowed_asset_ids:
            logger.warning(
                "resolve_assets: mentioned asset_id=%s is not bound to the scene; ignored",
                matched.id,
            )
            continue
        if matched and matched.id not in seen_ids:
            seen_ids.add(matched.id)
            requested_assets.append((matched, variant_name))
        elif not matched:
            logger.warning("resolve_assets: mention %r not found in assets", mention)

    subjects: list[dict[str, Any]] = []
    explicit_variant_ids = selected_variant_ids or {}
    for matched, mentioned_variant_name in requested_assets:
        variants = list(matched.variants)
        if matched.id in explicit_variant_ids:
            selected_variant_id = explicit_variant_ids[matched.id]
            variant = (
                _find_variant_by_id(selected_variant_id, variants)
                if selected_variant_id is not None
                else None
            )
            if selected_variant_id is not None and variant is None:
                logger.warning(
                    "resolve_assets: selected variant %s does not belong to asset_id=%s; using base asset",
                    selected_variant_id,
                    matched.id,
                )
        else:
            variant = (
                _find_variant(mentioned_variant_name, variants)
                if mentioned_variant_name
                else _find_chapter_variant(chapter_number, variants)
            )
        images = _collect_images(matched, variant)
        logger.info(
            "resolve_assets: asset_id=%s variant_id=%s images=%d (main=%s, a1=%s, a2=%s)",
            matched.id, variant.id if variant else None, len(images),
            bool(matched.main_image), bool(matched.angle_image_1), bool(matched.angle_image_2),
        )
        subjects.append({
            "name": (
                f"{matched.canonical_name}#{variant.name}"
                if variant and mentioned_variant_name
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


def _find_variant_by_id(
    variant_id: int,
    variants: list[AssetVariant],
) -> AssetVariant | None:
    return next((variant for variant in variants if variant.id == variant_id), None)


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
    return images


def resolve_image_source(path: str) -> str:
    """远程图片保留 URL，本地与 /media/ 图片转换为 Base64 data URI。"""
    if path.startswith(("http://", "https://", "data:")):
        return path
    if path.startswith("/media/"):
        path = os.path.join(settings.MEDIA_PATH, path[len("/media/"):])
    return image_to_base64(path)
