"""Keep multiple visual forms through persistence and repeated chapter extraction."""
import json

import pytest

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.novel import Novel
from services.extraction.extractor import AssetExtractionResult
from services.extraction.persistence import AssetUpsertService


def entries():
    return [
        {'name': '主角', 'description': '当前形象', 'base_traits': '基础完整设计'},
        {'name': '主角', 'base_traits': '基础完整设计', 'variant': {'name': '前世', 'base_traits': '现代少年完整设计', 'change_reason': '前世闪回'}},
        {'name': '主角', 'base_traits': '基础完整设计', 'variant': {'name': '襁褓', 'base_traits': '婴儿完整设计', 'change_reason': '幼年闪回'}},
    ]














@pytest.mark.asyncio
async def test_multiple_forms_save_idempotently_without_changing_base_design_or_media():
    novel = await Novel.create(name='同章多个形态')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主角',
        base_traits='用户确认的基础设计', main_image='/media/base.png', metadata={'voice_reference_id': 17})
    accepted = AssetExtractionResult.model_validate({'persons': entries()[::-1], 'scenes': [], 'items': []})
    service = AssetUpsertService()
    first = await service.save_result(novel_id=novel.id, chapter_number=1, result=accepted, include_ids=True)
    second = await service.save_result(novel_id=novel.id, chapter_number=1, result=accepted, include_ids=True)
    assert [r.get('variant_id') for r in first['persons']] == [r.get('variant_id') for r in second['persons']]
    variants = await AssetVariant.filter(asset=asset).order_by('name')
    assert len(variants) == 2 and all(v.chapter_numbers == [1] for v in variants)
    assert {v.name: v.base_traits for v in variants} == {'前世': '现代少年完整设计', '襁褓': '婴儿完整设计'}
    assert await Asset.filter(novel=novel).count() == 1
    await asset.refresh_from_db()
    assert asset.base_traits == '用户确认的基础设计'
    assert asset.main_image == '/media/base.png' and asset.metadata['voice_reference_id'] == 17


@pytest.mark.asyncio
async def test_manual_create_and_patch_keep_same_chapter_forms_and_explicit_bindings():
    from controllers.asset import asset_controller
    from schemas.asset_variant import AssetVariantCreate, AssetVariantPatch
    from fastapi import HTTPException
    from services.creation_objects import CreationObjects
    from services.video.asset_resolver import resolve_assets

    novel = await Novel.create(name='同章形态编辑')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主角', main_image='https://example.test/base.png')
    first = await asset_controller.create_variant(asset.id, AssetVariantCreate(name='前世', chapter_numbers=[1],
        base_traits='现代少年设计', images=['https://example.test/previous.png']))
    second = await asset_controller.create_variant(asset.id, AssetVariantCreate(name='襁褓', chapter_numbers=[1],
        base_traits='婴儿设计', images=['https://example.test/baby.png']))
    await asset_controller.patch_variant(asset.id, second.id, AssetVariantPatch(chapter_numbers=[1, 2]))
    await first.refresh_from_db()
    assert first.chapter_numbers == [1]
    with pytest.raises(HTTPException) as duplicate:
        await asset_controller.create_variant(asset.id, AssetVariantCreate(name='前世', chapter_numbers=[2]))
    assert duplicate.value.status_code == 409
    foreign = await Asset.create(novel=novel, asset_type=1, canonical_name='其他角色')
    with pytest.raises(ValueError, match='绑定形态'):
        await CreationObjects(novel.id).validate_variant_bindings([foreign.id], {str(foreign.id): first.id})
    subjects = await resolve_assets('@{主角}、@{主角#前世}、@{主角#襁褓}', novel.id, chapter_number=1,
        selected_asset_ids=[asset.id], selected_variant_ids={asset.id: [None, first.id, second.id]})
    assert [row['name'] for row in subjects] == ['主角', '主角#前世', '主角#襁褓']




@pytest.mark.asyncio
async def test_reused_asset_and_second_episode_form_keep_one_parent_and_separate_chapters():
    novel = await Novel.create(name='跨章复用')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主角', source_chapters=[1],
        base_traits='已确认设计', main_image='/media/base.png', is_global=False)
    result = AssetExtractionResult.model_validate({'persons': [{
        'name': '主角', 'base_traits': '新生成的基础描述',
        'variant': {'name': '雨衣', 'base_traits': '蓝色雨衣', 'change_reason': '第二集下雨'},
    }], 'scenes': [], 'items': []})
    service = AssetUpsertService()
    for _ in range(2):
        await service.save_result(novel_id=novel.id, chapter_number=2, result=result, preserve_existing=True)
    await asset.refresh_from_db()
    assert await Asset.filter(novel=novel).count() == 1
    assert asset.source_chapters == [1, 2]
    assert asset.base_traits == '已确认设计' and asset.main_image == '/media/base.png'
    form = await AssetVariant.get(asset=asset)
    assert form.name == '雨衣' and form.chapter_numbers == [2]
    from services.storyboard.entities import entities_for_assets
    await asset.fetch_related('variants')
    assert entities_for_assets([asset], 1, {})[0].variant_id is None
    assert entities_for_assets([asset], 2, {asset.id: form.id})[0].variant_id == form.id
