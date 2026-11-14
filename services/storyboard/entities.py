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


def entities_for_assets(assets, chapter_number: int, selected: dict[int, int], prompt: str | None = None):
    """Use the same variant selection for fresh generation and existing scenes."""
    from schemas.scene import SceneEntity
    from services.video.asset_resolver import select_asset_variants, variant_selection_ids, _extract_asset_mentions
    from utils.enums import AssetTypeEnum
    from utils.messages import localized_message

    entities = []
    explicit_versions = {asset.id for asset, name in _extract_asset_mentions(prompt or '', list(assets)) if name}
    for asset in assets:
        if asset.id in explicit_versions:
            entities.extend(generation_entities_for_assets([asset], chapter_number, {}))
            continue
        variants = select_asset_variants(asset, chapter_number, selected)
        identifiers = variant_selection_ids(selected[asset.id]) if asset.id in selected else [None]
        if any(identifier is not None and variant is None for identifier, variant in zip(identifiers, variants)):
            raise ValueError(localized_message('已选择的资产形态不存在，请先修复素材绑定'))
        for variant in variants:
            source = variant or asset
            name = f'{asset.canonical_name}#{variant.name}' if variant and len(variants) > 1 else asset.canonical_name
            entities.append(SceneEntity(asset_id=asset.id, name=name,
                aliases=[*(asset.aliases or []), *([f'{asset.canonical_name}#{variant.name}'] if variant else [])],
                description=visual_entity_description(source.description, source.base_traits),
                asset_type=AssetTypeEnum(asset.asset_type).nickname,
                variant_id=variant.id if variant else None))

    return entities


def generation_entities_for_assets(assets, chapter_number: int, selected: dict[int, int]):
    """Offer each visual identity separately so shots can select a flashback or current form."""
    from schemas.scene import SceneEntity
    from utils.enums import AssetTypeEnum

    entities = []
    for asset in assets:
        if asset.asset_type not in (AssetTypeEnum.person.value, AssetTypeEnum.scene.value, AssetTypeEnum.item.value):
            continue
        if asset.id in selected:
            entities.extend(entities_for_assets([asset], chapter_number, selected))
            continue
        entities.append(SceneEntity(asset_id=asset.id, name=asset.canonical_name,
            aliases=asset.aliases or [],
            description=visual_entity_description(asset.description, asset.base_traits),
            asset_type=AssetTypeEnum(asset.asset_type).nickname))
        for variant in asset.variants:
            entities.append(SceneEntity(asset_id=asset.id, variant_id=variant.id,
                name=f'{asset.canonical_name}#{variant.name}', aliases=[],
                description=visual_entity_description(variant.description, variant.base_traits),
                asset_type=AssetTypeEnum(asset.asset_type).nickname,
                chapter_numbers=list(variant.chapter_numbers or [])))
    return entities


def shot_variant_bindings(shot, entities):
    from prompts.storyboard import referenced_entities
    from services.video.asset_resolver import add_variant_binding

    bindings = {}
    for entity in referenced_entities(shot, entities):
        if entity.asset_id is not None:
            add_variant_binding(bindings, entity.asset_id, entity.variant_id)
    return bindings
