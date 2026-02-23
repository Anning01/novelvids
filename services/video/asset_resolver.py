"""解析 prompt 中的 @资产昵称，查找匹配资产并收集参考图。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from models.asset import Asset
from services.video.base import image_to_base64
from config import settings

logger = logging.getLogger(__name__)

# 匹配 @{多字名称} 或 @单字名称（兼容旧格式）
MENTION_PATTERN = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")


async def resolve_assets(prompt: str, novel_id: int) -> list[dict[str, Any]]:
    """从 prompt 中解析 @mentions，返回 subjects 列表。"""
    mentions = [m1 or m2 for m1, m2 in MENTION_PATTERN.findall(prompt)]
    logger.info("resolve_assets: mentions=%s (prompt[:100]=%r)", mentions, prompt[:100])
    if not mentions:
        return []

    # 查找该小说下的所有资产（一次查询）
    assets = await Asset.filter(novel_id=novel_id).all()
    logger.info(
        "resolve_assets: novel_id=%s, total_assets=%d, names=%s",
        novel_id, len(assets), [a.canonical_name for a in assets],
    )

    subjects: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for name in mentions:
        matched = _find_asset(name, assets)
        if matched and matched.id not in seen_ids:
            seen_ids.add(matched.id)
            images = _collect_images(matched)
            logger.info(
                "resolve_assets: matched %r -> asset_id=%s, images=%d (main=%s, a1=%s, a2=%s)",
                name, matched.id, len(images),
                bool(matched.main_image), bool(matched.angle_image_1), bool(matched.angle_image_2),
            )
            subjects.append({
                "name": matched.canonical_name,
                "images": images,
                "description": matched.description or matched.base_traits or "",
            })
        elif not matched:
            logger.warning("resolve_assets: mention %r not found in assets", name)

    return subjects


def _find_asset(name: str, assets: list[Asset]) -> Asset | None:
    """在资产列表中按 canonical_name 或 aliases 匹配。"""
    for asset in assets:
        if asset.canonical_name == name:
            return asset
        if name in (asset.aliases or []):
            return asset
    return None


def _collect_images(asset: Asset) -> list[str]:
    """收集资产的所有参考图（URL 直接返回，本地路径转 base64）。"""
    images: list[str] = []
    for field_name in ("main_image", "angle_image_1", "angle_image_2"):
        path = getattr(asset, field_name, None)
        if not path:
            continue
        # 远程 URL 直接使用
        if path.startswith(("http://", "https://")):
            images.append(path)
            continue
        # /media/... 路径 → 转换为本地绝对路径再转 base64
        if path.startswith("/media/"):
            path = os.path.join(settings.MEDIA_PATH, path[len("/media/"):])
        # 本地文件转 base64
        try:
            images.append(image_to_base64(path))
        except FileNotFoundError:
            logger.warning("resolve_assets: image not found: %s", path)
            continue
    return images
