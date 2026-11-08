"""Validate remake designs with the same asset protocol used by extraction and editing."""

from services.extraction.extractor import validate_asset_design
from prompts.creation_standards import render_asset_design


def render_remake_assets(assets, snapshot, language: str, aspect_ratio: str):
    result = {}
    for field, kind in (('characters', 'person'), ('scenes', 'scene'), ('objects', 'item')):
        result[field] = []
        for item in assets.get(field, []):
            asset_kind = 'group' if kind == 'person' and item.get('label') == '群像' else kind
            result[field].append({**item, 'description': render_asset_design(item['description'],
                item.get('visual_fields', {}), asset_kind, snapshot, language, aspect_ratio)})
    return result


def validate_remake_assets(assets, snapshot, language: str, aspect_ratio: str) -> None:
    for field, kind in (('characters', 'person'), ('scenes', 'scene'), ('objects', 'item')):
        for item in assets.get(field, []):
            asset_kind = 'group' if kind == 'person' and item.get('label') == '群像' else kind
            validate_asset_design(item['description'], asset_kind, snapshot, language, aspect_ratio)
