"""Render remake asset prompts from model-authored designs."""

from prompts.creation_standards import render_asset_design
from services.remake.identity_evidence import IDENTITY_EVIDENCE_FIELD


def render_remake_assets(assets, snapshot, language: str, aspect_ratio: str):
    result = {}
    for field, kind in (('characters', 'person'), ('scenes', 'scene'), ('objects', 'item')):
        result[field] = []
        for item in assets.get(field, []):
            asset_kind = 'group' if kind == 'person' and item.get('label') == '群像' else kind
            visual = {k: v for k, v in item.get('visual_fields', {}).items() if k != IDENTITY_EVIDENCE_FIELD}
            prompt = render_asset_design(item['description'], visual,
                asset_kind, snapshot, language, aspect_ratio)
            result[field].append({**item, 'description': prompt})
    return result
