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


def shot_variant_bindings(shot, entities) -> dict[str, int | None]:
    from prompts.storyboard import referenced_entities
    from utils.messages import localized_message

    bindings = {}
    for entity in referenced_entities(shot, entities):
        if entity.asset_id is None:
            continue
        key = str(entity.asset_id)
        if key in bindings and bindings[key] != entity.variant_id:
            raise ValueError(localized_message('同一镜头引用了同一资产的多个形态，请按形态拆分镜头'))
        bindings[key] = entity.variant_id
    return bindings
