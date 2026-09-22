from datetime import datetime, timezone
import asyncio

import pytest
from tortoise import Tortoise

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from services.creation_objects import CreationObjects, project_write


async def objects():
    novel = await Novel.create(name="CRUD隔离回归")
    chapter = await Chapter.create(novel=novel, number=1, name="雨夜", content="合成测试")
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name="林夏", source_chapters=[1])
    scenes = [await Scene.create(chapter=chapter, sequence=i, description=f"分镜{i}") for i in range(1, 4)]
    return novel, chapter, asset, scenes


@pytest.mark.asyncio
async def test_ordinary_page_creation_uses_the_transaction_connection():
    # Includes create() without an enclosing caller transaction. ORM create()
    # passes a pre-resolved client into our save override.
    novel, _, asset, scenes = await asyncio.wait_for(objects(), timeout=3)
    asset.description = '普通页面保存'
    await asyncio.wait_for(asset.save(), timeout=3)
    assert (await Asset.get(id=asset.id)).description == '普通页面保存'
    assert await Scene.filter(chapter__novel_id=novel.id).count() == len(scenes)


@pytest.mark.asyncio
async def test_archive_scene_preserves_video_and_restores_order_and_bindings():
    novel, chapter, asset, scenes = await objects()
    scene = scenes[1]
    await scene.assets.add(asset)
    video = await Video.create(scene=scene, model_type=1, status=3, url="keep.mp4")
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        snapshot = await service.archive("scene", scene.id)
    assert not await Scene.filter(id=scene.id).exists()
    assert await Scene.filter(chapter=chapter).order_by('sequence').values_list('sequence', flat=True) == [1, 2]
    assert await Video.filter(id=video.id).exists()
    await asset.fetch_related('scenes')
    assert scene.id not in [item.id for item in asset.scenes]
    async with project_write(novel.id):
        restored = await service.restore("scene", scene.id, snapshot)
    assert restored.sequence == 2
    assert await Scene.filter(chapter=chapter).order_by('sequence').values_list('id', flat=True) == [item.id for item in scenes]
    assert await restored.assets.all().values_list('id', flat=True) == [asset.id]


@pytest.mark.asyncio
async def test_asset_and_variant_queries_and_relations_hide_deleted_objects():
    novel, _, asset, _ = await objects()
    variant = await AssetVariant.create(asset=asset, name="雨衣", chapter_numbers=[1])
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        await service.archive('variant', variant.id)
    await asset.fetch_related('variants')
    assert not list(asset.variants)
    assert not await AssetVariant.filter(id=variant.id).exists()
    assert await AssetVariant.with_deleted().filter(id=variant.id).exists()
    async with project_write(novel.id):
        await service.archive('asset', asset.id)
    assert not await Asset.filter(id=asset.id).exists()
    assert await AssetVariant.with_deleted().filter(id=variant.id).exists()


@pytest.mark.asyncio
async def test_in_use_assets_and_running_scenes_cannot_be_archived():
    novel, _, asset, scenes = await objects()
    await scenes[0].assets.add(asset)
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        with pytest.raises(ValueError, match='引用'):
            await service.archive('asset', asset.id)
    await Video.create(scene=scenes[0], model_type=1, status=2)
    async with project_write(novel.id):
        with pytest.raises(ValueError, match='生成|任务'):
            await service.archive('scene', scenes[0].id)
    assert await Scene.filter(id=scenes[0].id).exists()
    assert await Asset.filter(id=asset.id).exists()


@pytest.mark.asyncio
async def test_insert_move_and_archive_share_contiguous_order():
    novel, chapter, _, scenes = await objects()
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        added = await service.create_scene(chapter.id, after_id=scenes[0].id, values={'description': '插入', 'prompt': ''})
        await service.move_scene(added, after_id=scenes[2].id)
    assert await Scene.filter(chapter=chapter).order_by('sequence').values_list('id', flat=True) == [s.id for s in scenes] + [added.id]
    assert await Scene.filter(chapter=chapter).order_by('sequence').values_list('sequence', flat=True) == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_archived_scene_cannot_be_resurrected_by_stale_callback_save():
    novel, _, _, scenes = await objects()
    stale = scenes[0]
    async with project_write(novel.id):
        await CreationObjects(novel.id).archive('scene', stale.id)
    stale.prompt = '迟到的生成结果'
    with pytest.raises(ValueError, match='移除|删除'):
        await stale.save()
    assert not await Scene.filter(id=stale.id).exists()


@pytest.mark.asyncio
async def test_safe_schema_generation_preserves_deleted_state():
    _, _, asset, _ = await objects()
    await Asset.filter(id=asset.id).update(deleted_at=datetime.now(timezone.utc))
    await Tortoise.generate_schemas(safe=True)
    await Tortoise.generate_schemas(safe=True)
    assert not await Asset.filter(id=asset.id).exists()
    assert await Asset.with_deleted().filter(id=asset.id).exists()


@pytest.mark.asyncio
async def test_old_database_columns_are_added_without_changing_existing_objects(monkeypatch):
    from services.schema_compat import ensure_creation_agent_schema
    _, _, asset, scenes = await objects()
    connection = Tortoise.get_connection('default')
    monkeypatch.setattr('services.schema_compat.settings.DATABASE_URL', 'sqlite://:memory:')
    for table in ('assets', 'asset_variants', 'scenes'):
        await connection.execute_script(f'ALTER TABLE {table} DROP COLUMN deleted_at;')
    try:
        await ensure_creation_agent_schema()
        await ensure_creation_agent_schema()
        assert (await Asset.get(id=asset.id)).canonical_name == asset.canonical_name
        assert (await Scene.get(id=scenes[0].id)).description == scenes[0].description
        for table in ('assets', 'asset_variants', 'scenes'):
            columns = await connection.execute_query_dict(f'PRAGMA table_info({table})')
            assert len([column for column in columns if column['name'] == 'deleted_at']) == 1
    finally:
        await ensure_creation_agent_schema()


@pytest.mark.asyncio
async def test_restoring_asset_restores_only_variants_removed_with_it():
    novel, _, asset, _ = await objects()
    previous = await AssetVariant.create(asset=asset, name='旧形态')
    current = await AssetVariant.create(asset=asset, name='新形态')
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        await service.archive('variant', previous.id)
        recovery = await service.archive('asset', asset.id)
        await service.restore('asset', asset.id, recovery)
    assert await AssetVariant.filter(id=current.id).exists()
    assert not await AssetVariant.filter(id=previous.id).exists()


@pytest.mark.asyncio
async def test_variant_restore_cannot_replace_a_new_chapter_assignment():
    novel, _, asset, _ = await objects()
    service = CreationObjects(novel.id)
    old = await AssetVariant.create(asset=asset, name='旧雨衣', chapter_numbers=[1])
    async with project_write(novel.id):
        recovery = await service.archive('variant', old.id)
        current = await service.create_variant(asset.id, {'name': '新雨衣', 'chapter_numbers': [1]})
    async with project_write(novel.id):
        with pytest.raises(ValueError, match='已有形态'):
            await service.restore('variant', old.id, recovery)
    assert not await AssetVariant.filter(id=old.id).exists()
    assert (await AssetVariant.get(id=current.id)).chapter_numbers == [1]


@pytest.mark.asyncio
async def test_manual_merge_cannot_destroy_archived_scene_recovery_bindings():
    from fastapi import HTTPException
    from controllers.asset import asset_controller

    novel, _, asset, scenes = await objects()
    target = await Asset.create(novel=novel, asset_type=1, canonical_name='另一个角色')
    await scenes[0].assets.add(asset)
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        snapshot = await service.archive('scene', scenes[0].id)
    with pytest.raises(HTTPException, match='恢复'):
        await asset_controller.merge(asset.id, target.id)
    async with project_write(novel.id):
        restored = await service.restore('scene', scenes[0].id, snapshot)
    assert await restored.assets.all().values_list('id', flat=True) == [asset.id]


@pytest.mark.asyncio
async def test_generated_scene_batch_rolls_back_if_a_reference_was_removed():
    from schemas.scene import SceneEntity, Storyboard
    from services.storyboard.handler import StoryboardTaskHandler
    from test.test_services.test_storyboard_handler import _shot

    novel, chapter, asset, scenes = await objects()
    entity = SceneEntity(name=asset.canonical_name, asset_id=asset.id, description='完整的人物设定', asset_type='人物', aliases=[])
    async with project_write(novel.id):
        await CreationObjects(novel.id).archive('asset', asset.id)
    generated = Storyboard(shots=[_shot(1, '空站台。'), _shot(2, '@{林夏}独自站着。')])
    with pytest.raises(ValueError, match='移除'):
        await StoryboardTaskHandler()._save_scenes(chapter.id, generated, {}, 0, entities=[entity])
    assert await Scene.filter(chapter=chapter).order_by('sequence').values_list('id', flat=True) == [scene.id for scene in scenes]


@pytest.mark.asyncio
async def test_restore_rejects_later_changes_to_archived_content_and_variant_media():
    novel, _, asset, scenes = await objects()
    variant = await AssetVariant.create(asset=asset, name='雨衣', images=['before.png'])
    service = CreationObjects(novel.id)
    async with project_write(novel.id):
        scene_snapshot = await service.archive('scene', scenes[0].id)
        asset_snapshot = await service.archive('asset', asset.id)
    await Scene.with_deleted().filter(id=scenes[0].id).update(description='后续修改')
    await AssetVariant.with_deleted().filter(id=variant.id).update(images=['later.png'])
    async with project_write(novel.id):
        with pytest.raises(ValueError, match='后续修改'):
            await service.restore('scene', scenes[0].id, scene_snapshot)
        with pytest.raises(ValueError, match='后续修改'):
            await service.restore('asset', asset.id, asset_snapshot)
    assert not await Scene.filter(id=scenes[0].id).exists()
    assert not await Asset.filter(id=asset.id).exists()
