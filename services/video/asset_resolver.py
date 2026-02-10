"""解析 prompt 中的 @资产昵称，查找匹配资产并收集参考图。"""

from __future__ import annotations

import re
from typing import Any

from models.asset import Asset
from services.video.base import image_to_base64


# 匹配 @资产昵称 (@后面跟中英文、数字、下划线)
MENTION_PATTERN = re.compile(r"@([\w\u4e00-\u9fff]+)")


async def resolve_assets(prompt: str, novel_id: int) -> list[dict[str, Any]]:
    """从 prompt 中解析 @mentions，返回 subjects 列表。

    每个 subject 形如:
        {"name": "张三", "images": ["data:image/png;base64,..."]}

    Args:
        prompt: 包含 @资产昵称 的文本。
        novel_id: 所属小说ID，用于限定资产查找范围。

    Returns:
        适用于视频生成 API 的 subjects 列表。
    """
    mentions = MENTION_PATTERN.findall(prompt)
    if not mentions:
        return []

    # 查找该小说下的所有资产（一次查询）
    assets = await Asset.filter(novel_id=novel_id).all()

    subjects: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for name in mentions:
        matched = _find_asset(name, assets)
        if matched and matched.id not in seen_ids:
            seen_ids.add(matched.id)
            images = _collect_images(matched)
            subjects.append({"name": matched.canonical_name, "images": images})

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
    """收集资产的所有参考图（转为 base64 data URI）。"""
    images: list[str] = []
    for field_name in ("main_image", "angle_image_1", "angle_image_2"):
        path = getattr(asset, field_name, None)
        if not path:
            continue
        try:
            images.append(image_to_base64(path))
        except FileNotFoundError:
            continue
    return images
