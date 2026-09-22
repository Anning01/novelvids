from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from controllers.scene import scene_controller
from controllers.asset import asset_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from schemas.scene import ScenePatch
from schemas.asset import AssetPatch, AssetUpdate
from schemas.asset_variant import AssetVariantPatch
from test.test_services.test_creation_agent_tools import setup_service
from schemas.creation_agent import StoryboardPromptEdit, ImagePromptEdit
from services.creation_agent.tools import prompt_version


@pytest.mark.asyncio
async def test_stale_manual_scene_save_cannot_overwrite_agent_or_clear_bindings():
    service, scene, asset, _, _ = await setup_service()
    await scene.assets.add(asset)
    await scene.refresh_from_db()
    original = scene.prompt
    await service.update_storyboard_prompt([StoryboardPromptEdit(scene_id=scene.id,
        expected_version=prompt_version(scene), legacy_prompt='空站台笼罩在柔和光线中。')], tool_call_id='agent-write')
    with pytest.raises(HTTPException) as conflict:
        await scene_controller.patch(scene.id, ScenePatch(prompt='过期手工草稿', expected_prompt=original, asset_ids=[]))
    assert conflict.value.status_code == 409
    await scene.refresh_from_db()
    assert scene.prompt == '空站台笼罩在柔和光线中。'
    assert await scene.assets.all().values_list('id', flat=True) == [asset.id]
    updated = await scene_controller.patch(scene.id, ScenePatch(prompt='核对后的修改', expected_prompt=scene.prompt))
    assert updated.prompt == '核对后的修改'


@pytest.mark.asyncio
async def test_stale_asset_and_variant_edit_preserve_new_prompt():
    service, _, asset, variant, _ = await setup_service()
    for kind, item in [('asset', asset), ('variant', variant)]:
        await service.update_image_prompt([ImagePromptEdit(target_kind=kind, target_id=item.id,
            expected_version=prompt_version(item), prompt='助手新提示词')], tool_call_id=kind)
    with pytest.raises(HTTPException) as conflict:
        await asset_controller.patch(asset.id, AssetPatch(base_traits='过期草稿', expected_prompt=asset.base_traits))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException):
        await asset_controller.patch_variant(asset.id, variant.id, AssetVariantPatch(base_traits='过期形态', expected_prompt=variant.base_traits))
    assert (await Asset.get(id=asset.id)).base_traits == '助手新提示词'
    assert (await AssetVariant.get(id=variant.id)).base_traits == '助手新提示词'


@pytest.mark.asyncio
async def test_legacy_patch_without_precondition_remains_supported_and_advances_version():
    _, scene, _, _, _ = await setup_service()
    version = scene.updated_at
    updated = await scene_controller.patch(scene.id, ScenePatch(prompt='旧客户端正常保存'))
    assert updated.prompt == '旧客户端正常保存'
    assert updated.updated_at > version


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['update', 'patch', 'variant'])
@pytest.mark.parametrize('stale', [False, True])
async def test_prompt_precondition_preserves_image_derivatives(monkeypatch, operation, stale):
    """合并后，版本检查成功仍生成缩略图，冲突则不写入图片或生成派生图。"""
    _, _, asset, variant, _ = await setup_service()
    item = variant if operation == 'variant' else asset
    original_prompt = item.base_traits
    original_images = list(variant.images) if operation == 'variant' else asset.main_image
    image = 'uploads/agent-sync/revised.png'
    derivatives = AsyncMock()
    monkeypatch.setattr('controllers.asset.ensure_image_derivatives', derivatives)
    changes = {
        'base_traits': '核对后的新提示词',
        'expected_prompt': '过期提示词' if stale else original_prompt,
    }

    if operation == 'variant':
        save = asset_controller.patch_variant(
            asset.id, variant.id, AssetVariantPatch(**changes, images=[image]),
        )
    elif operation == 'update':
        save = asset_controller.update(asset.id, AssetUpdate(
            **changes, main_image=image, novel_id=asset.novel_id,
            asset_type=asset.asset_type, canonical_name=asset.canonical_name,
        ))
    else:
        save = asset_controller.patch(asset.id, AssetPatch(**changes, main_image=image))

    if stale:
        with pytest.raises(HTTPException) as conflict:
            await save
        assert conflict.value.status_code == 409
        derivatives.assert_not_awaited()
    else:
        saved = await save
        assert saved.base_traits == changes['base_traits']
        derivatives.assert_awaited_once_with(image)

    await item.refresh_from_db()
    assert item.base_traits == (original_prompt if stale else changes['base_traits'])
    stored_images = item.images if operation == 'variant' else item.main_image
    expected_images = [image] if operation == 'variant' else image
    assert stored_images == (original_images if stale else expected_images)
