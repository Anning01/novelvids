"""Reload saved project identities independently of conversation summaries."""

import json

from prompts.project_settings import audiovisual_guidance

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.novel import Novel
from services.creation_agent.catalog import CreationCatalog

CATALOG_PATH = '/project_facts/registered-assets.jsonl'


async def load_project_facts(*, novel_id, chapter_id, page_size, character_budget, authorize):
    await authorize()
    project = await Novel.get(id=novel_id)
    catalog = CreationCatalog(novel_id, chapter_id)
    chapter = await catalog.objects.chapter(chapter_id) if chapter_id else None
    active_ids = set(await catalog.chapter_asset_ids(chapter)) if chapter else set()
    assets = await Asset.filter(novel_id=novel_id, asset_type__in=[1, 2, 3]).order_by('id').values(
        'id', 'canonical_name', 'aliases', 'asset_type', 'source_chapters', 'is_global', 'description')
    variants = await AssetVariant.filter(asset__novel_id=novel_id, asset__deleted_at__isnull=True,
        asset__asset_type__in=[1, 2, 3]).order_by('id').values('id', 'asset_id', 'name', 'chapter_numbers', 'description')
    by_asset = {}
    for variant in variants:
        by_asset.setdefault(variant['asset_id'], []).append({
            'kind': 'variant', 'id': variant['id'], 'asset_id': variant['asset_id'], 'name': variant['name'],
            'chapter_numbers': variant['chapter_numbers'], 'description': (variant['description'] or '')[:240],
        })
    rows = [{
        'kind': 'asset', 'id': asset['id'], 'name': asset['canonical_name'], 'aliases': asset['aliases'],
        'asset_type': asset['asset_type'], 'source_chapters': asset['source_chapters'], 'is_global': asset['is_global'],
        'description': (asset['description'] or '')[:240], 'variants': by_asset.get(asset['id'], []),
    } for asset in assets]
    world = {'project_id': project.id, 'style_key': project.style_key,
        'custom_style_prompt': (project.custom_style_prompt or '')[:character_budget],
        'project_setting': (project.project_setting or '')[:character_budget],
        'storyboard_enabled': project.storyboard_enabled, 'audiovisual_guidance': audiovisual_guidance(project.audiovisual_guidance), 'shot_duration_max': project.shot_duration_max,
        'aspect_ratio': project.aspect_ratio, 'storyboard_strategy': project.storyboard_strategy}
    relevant = [row for row in rows if row['id'] in active_ids] if chapter else rows
    preview, used = [], 0
    for row in relevant or rows:
        size = len(json.dumps(row, ensure_ascii=False))
        if len(preview) >= page_size or used + size > character_budget:
            break
        preview.append(row)
        used += size
    summary = {'world_and_style': world, 'chapter_number': chapter.number if chapter else None,
        'saved_assets': len(rows), 'saved_variants': len(variants), 'catalog_path': CATALOG_PATH,
        'asset_groups': preview, 'preview_has_more': len(relevant or rows) > len(preview),
        'source': 'current_saved_project_catalog'}
    entries = [{'world_and_style': world}]
    for row in rows:
        entries.append({key: value for key, value in row.items() if key != 'variants'})
        entries.extend({**variant, 'asset_name': row['name']} for variant in row['variants'])
    manifest = '\n'.join(json.dumps(item, ensure_ascii=False) for item in entries)
    return summary, manifest
