"""Share current visual definitions between generation and prompt editing."""

import re

from prompts.reference import (
    REFERENCE_OUTPUT_GUARD_EN,
    REFERENCE_OUTPUT_GUARD_ZH,
    is_complete_reference_prompt,
)


def visual_entity_description(description: str | None, prompt: str | None) -> str:
    """Unwrap the repository's reference-sheet format, preserving custom text."""
    traits = (prompt or '').strip()
    if is_complete_reference_prompt(traits):
        match = re.search(r'(?:角色描述[：:]|场景描述[：:]|Character description:|Scene description:|【道具描述】|\[Prop description\])\s*', traits)
        if match:
            traits = traits[match.end():].strip()
            for guard in (REFERENCE_OUTPUT_GUARD_ZH, REFERENCE_OUTPUT_GUARD_EN):
                traits = traits.removesuffix(guard).strip()
    return '\n'.join(dict.fromkeys(value for value in ((description or '').strip(), traits) if value))


def entities_for_assets(assets, chapter_number: int, selected: dict[int, int]):
    """Use the same variant selection for fresh generation and existing scenes."""
    from schemas.scene import SceneEntity
    from services.video.asset_resolver import select_asset_variant
    from utils.enums import AssetTypeEnum
    from utils.messages import localized_message

    entities = []
    for asset in assets:
        variant = select_asset_variant(asset, chapter_number, selected)
        if selected.get(asset.id) is not None and variant is None:
            raise ValueError(localized_message('已选择的资产形态不存在，请先修复素材绑定'))
        source = variant or asset
        entities.append(SceneEntity(asset_id=asset.id, name=asset.canonical_name,
            aliases=[*(asset.aliases or []), *([f'{asset.canonical_name}#{variant.name}'] if variant else [])],
            description=visual_entity_description(source.description, source.base_traits),
            asset_type=AssetTypeEnum(asset.asset_type).nickname))
    return entities
