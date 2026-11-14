"""解析 prompt 中的 @资产昵称，查找匹配资产并收集参考图。"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from models.asset import Asset
from models.asset_variant import AssetVariant
from services.image_inputs import resolve_image_source
from utils.messages import localized_message

logger = logging.getLogger(__name__)

# 匹配 @{多字名称} 或 @单字名称（兼容旧格式）
MENTION_PATTERN = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")


VariantSelection = int | None | list[int | None]


def variant_selection_ids(value: Any) -> list[int | None]:
    values = value if isinstance(value, list) else [value]
    if not values:
        raise ValueError('Empty variant selection')
    result = []
    for raw in values:
        if raw is None:
            identifier = None
        elif isinstance(raw, bool) or not str(raw).isdigit() or int(raw) < 1:
            raise ValueError('Invalid variant identifier')
        else:
            identifier = int(raw)
        if identifier not in result:
            result.append(identifier)
    return result


def compact_variant_selection(values: list[int | None]) -> VariantSelection:
    return values[0] if len(values) == 1 else values


def add_variant_binding(bindings: dict, asset_id: int, variant_id: int | None):
    key = str(asset_id)
    values = variant_selection_ids(bindings[key]) if key in bindings else []
    if variant_id not in values:
        values.append(variant_id)
    bindings[key] = compact_variant_selection(values)


def normalize_selected_variant_ids(value: Any) -> dict[int, VariantSelection]:
    """Read both legacy single-form bindings and simultaneous visual forms."""
    if not isinstance(value, dict):
        return {}
    selections = {}
    for raw_asset_id, raw in value.items():
        try:
            asset_id = int(raw_asset_id)
            identifiers = variant_selection_ids(raw)
        except (TypeError, ValueError):
            continue
        if asset_id > 0:
            selections[asset_id] = identifiers if isinstance(raw, list) else compact_variant_selection(identifiers)
    return selections


async def resolve_assets(
    prompt: str,
    novel_id: int,
    chapter_number: int | None = None,
    selected_asset_ids: Sequence[int] | None = None,
    selected_variant_ids: Mapping[int, VariantSelection] | None = None,
    *,
    include_selected: bool = False,
) -> list[dict[str, Any]]:
    """解析分镜使用的资产及形态，返回视频模型 subjects。

    只有同时满足“已绑定到分镜”和“在 prompt 中显式引用”的资产才会提交；
    专项稿可以补齐用户已绑定的资产。带 ``#形态`` 的引用按各自形态解析；同一资产可以同时引用基础与多个形态。
    """
    # 查找该小说下的所有资产（一次查询）
    assets = await Asset.filter(novel_id=novel_id).prefetch_related("variants")
    logger.info(
        "resolve_assets: novel_id=%s, total_assets=%d",
        novel_id, len(assets),
    )
    mentions = _extract_asset_mentions(prompt, assets)
    logger.info(
        "resolve_assets: matched_references=%d",
        len(mentions),
    )
    allowed_asset_ids = set(selected_asset_ids) if selected_asset_ids is not None else None
    requested_assets: list[tuple[Asset, str]] = []
    seen_versions: set[tuple[int, str]] = set()

    for matched, variant_name in mentions:
        if matched and allowed_asset_ids is not None and matched.id not in allowed_asset_ids:
            logger.warning(
                "resolve_assets: mentioned asset_id=%s is not bound to the scene; ignored",
                matched.id,
            )
            continue
        if matched and (matched.id, variant_name) not in seen_versions:
            seen_versions.add((matched.id, variant_name))
            requested_assets.append((matched, variant_name))

    if include_selected and allowed_asset_ids:
        mentioned_ids = {asset.id for asset, _ in requested_assets}
        requested_assets.extend(
            (asset, "") for asset in sorted(assets, key=lambda asset: asset.id)
            if asset.id in allowed_asset_ids and asset.id not in mentioned_ids
        )

    explicit_variant_ids = selected_variant_ids or {}
    resolved = []
    for matched, mentioned_variant_name in requested_assets:
        multiple_versions = sum(asset.id == matched.id for asset, _ in requested_assets) > 1
        if mentioned_variant_name:
            variant = _find_variant(mentioned_variant_name, list(matched.variants))
            if variant is None:
                raise ValueError(localized_message('引用的资产形态不存在或已移除，请重新选择'))
            selection = explicit_variant_ids.get(matched.id)
            # Legacy scalar bindings allow extra prompt references; lists record explicit choices.
            if isinstance(selection, list) and variant.id not in selection:
                continue
            resolved.append((matched, variant, True))
        elif multiple_versions and not isinstance(explicit_variant_ids.get(matched.id), list):
            resolved.append((matched, None, False))
        else:
            resolved.extend((matched, variant, False) for variant in select_asset_variants(matched, chapter_number, explicit_variant_ids))
    if include_selected and allowed_asset_ids:
        for asset in sorted(assets, key=lambda asset: asset.id):
            if asset.id in allowed_asset_ids:
                resolved.extend((asset, variant, False) for variant in select_asset_variants(asset, chapter_number, explicit_variant_ids))

    subjects: list[dict[str, Any]] = []
    seen = set()
    for matched, variant, qualified in resolved:
        identity = (matched.id, variant.id if variant else None)
        if identity in seen:
            continue
        seen.add(identity)
        multiple = len({item.id if item else None for asset, item, _ in resolved if asset.id == matched.id}) > 1
        subjects.append({
            "name": f"{matched.canonical_name}#{variant.name}" if variant and (qualified or multiple) else matched.canonical_name,
            "variant_name": variant.name if variant else None,
            "images": _collect_images(matched, variant),
            "description": (variant.description or variant.base_traits) if variant else matched.description or matched.base_traits or "",
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


def _extract_asset_mentions(
    prompt: str,
    assets: list[Asset],
) -> list[tuple[Asset, str]]:
    """按已登记名称解析引用，兼容 ``@羽宁沿着`` 这类无分隔旧语法。"""
    occurrences: dict[int, tuple[Asset, str, int]] = {}
    braced_ranges: list[tuple[int, int]] = []

    for match in re.finditer(r"@\{([^}]+)\}", prompt):
        braced_ranges.append(match.span())
        name, _, variant_name = match.group(1).partition("#")
        asset = _find_asset(name, assets)
        if asset is not None:
            occurrences[match.start()] = (asset, variant_name, len(match.group(0)))

    name_candidates = sorted(
        (
            (name, asset)
            for asset in assets
            for name in (asset.canonical_name, *(asset.aliases or []))
            if name
        ),
        key=lambda item: (-len(item[0]), item[0]),
    )
    for name, asset in name_candidates:
        syntax = f"@{name}"
        start = 0
        while (index := prompt.find(syntax, start)) >= 0:
            start = index + len(syntax)
            if any(left <= index < right for left, right in braced_ranges):
                continue
            variant_name = ""
            suffix_start = index + len(syntax)
            for variant in sorted(asset.variants, key=lambda item: -len(item.name)):
                variant_syntax = f"#{variant.name}"
                if prompt.startswith(variant_syntax, suffix_start):
                    variant_name = variant.name
                    break
            consumed = len(syntax) + (len(variant_name) + 1 if variant_name else 0)
            existing = occurrences.get(index)
            if existing is None or consumed > existing[2]:
                occurrences[index] = (asset, variant_name, consumed)

    return [
        (asset, variant_name)
        for _, (asset, variant_name, _) in sorted(occurrences.items())
    ]


def select_asset_variant(
    asset: Asset,
    chapter_number: int | None,
    selected_variant_ids: Mapping[int, VariantSelection],
    mentioned_variant_name: str = "",
) -> AssetVariant | None:
    """Shared visual-version precedence for prompt context and media generation."""
    return select_asset_variants(asset, chapter_number, selected_variant_ids, mentioned_variant_name)[0]


def select_asset_variants(
    asset: Asset,
    chapter_number: int | None,
    selected_variant_ids: Mapping[int, VariantSelection],
    mentioned_variant_name: str = "",
) -> list[AssetVariant | None]:
    variants = list(asset.variants)
    if asset.id in selected_variant_ids:
        return [_find_variant_by_id(identifier, variants) if identifier is not None else None
                for identifier in variant_selection_ids(selected_variant_ids[asset.id])]
    if mentioned_variant_name:
        return [_find_variant(mentioned_variant_name, variants)]
    return [_find_chapter_variant(chapter_number, variants)]


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
