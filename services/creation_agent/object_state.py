"""Snapshots and field restoration for durable, reversible creation changes."""

from copy import deepcopy
from datetime import datetime, timezone

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.scene import Scene
from services.creation_agent.tools import _digest
from services.creation_objects import CreationObjects


async def object_state(target) -> dict:
    if isinstance(target, Scene):
        return {'description': target.description, 'prompt': target.prompt,
                'prompt_params': deepcopy(target.prompt_params), 'duration': target.duration,
                'asset_ids': sorted(await target.assets.all().values_list('id', flat=True)),
                'variant_bindings': deepcopy((target.metadata or {}).get('asset_variant_ids', {}))}
    if isinstance(target, Asset):
        return {name: deepcopy(getattr(target, name)) for name in (
            'canonical_name', 'aliases', 'description', 'base_traits', 'source_chapters', 'is_global', 'last_updated_chapter')}
    return {name: deepcopy(getattr(target, name)) for name in ('name', 'description', 'base_traits', 'chapter_numbers')}


async def object_version(target) -> str:
    data = await object_state(target)
    return _digest({'state': data, 'updated_at': target.updated_at, 'deleted_at': target.deleted_at,
                    **({'sequence': target.sequence} if isinstance(target, Scene) else {})})


async def creation_version(target) -> str:
    # Automatic reordering changes sequence/updated_at during the same batch.
    # User content, references and media settings are the undo precondition.
    extra_fields = ('metadata', 'status') if isinstance(target, Scene) else (
        ('metadata', 'images') if isinstance(target, AssetVariant) else ('metadata', 'main_image', 'angle_image_1', 'angle_image_2', 'image_source'))
    return _digest({'fields': await object_state(target), **{key: getattr(target, key) for key in extra_fields}})


async def write_fields(objects: CreationObjects, target, fields: dict):
    values = deepcopy(fields)
    if isinstance(target, AssetVariant) and 'chapter_numbers' in values:
        await objects.ensure_variant_chapters(target.asset_id, values['chapter_numbers'], exclude_id=target.id)
    if isinstance(target, Scene):
        asset_ids = values.get('asset_ids', await target.assets.all().values_list('id', flat=True))
        bindings = values.get('variant_bindings', (target.metadata or {}).get('asset_variant_ids') or {})
        await objects.validate_variant_bindings(asset_ids, bindings)
        if 'asset_ids' in values:
            await objects.bind_assets(target, values.pop('asset_ids'))
        if 'variant_bindings' in values:
            values['metadata'] = {**(target.metadata or {}), 'asset_variant_ids': values.pop('variant_bindings')}
    if values:
        values['updated_at'] = datetime.now(timezone.utc)
        changed = await type(target).filter(id=target.id).update(**values)
        if not changed:
            raise ValueError('对象已被移除，请重新读取')
    await target.refresh_from_db()


async def object_label(target) -> str:
    if isinstance(target, Scene):
        await target.fetch_related('chapter')
        return f'第 {target.chapter.number} 章 · 分镜 {target.sequence}'
    if isinstance(target, AssetVariant):
        parent = await Asset.get(id=target.asset_id)
        return f'{parent.canonical_name} · {target.name}'
    return target.canonical_name
