import asyncio

import pytest

from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import PromptChange
from models.novel import Novel
from models.scene import Scene
from schemas.creation_agent import ImagePromptEdit, StoryboardPromptEdit
from services.creation_agent.tools import PromptEditService, PromptEditConflict, prompt_version
from utils.enums import AssetTypeEnum, TaskStatusEnum


async def setup_service():
    novel = await Novel.create(name="创作工具回归")
    chapter = await Chapter.create(novel=novel, number=1, name="雨夜", content="合成文本")
    scene = await Scene.create(chapter=chapter, sequence=5, prompt="空站台", duration=6, metadata={"keep": "metadata"})
    asset = await Asset.create(novel=novel, canonical_name="女主", asset_type=AssetTypeEnum.person.value, base_traits="灰色风衣", main_image="keep.png")
    variant = await AssetVariant.create(asset=asset, name="雨夜", base_traits="雨夜风衣", chapter_numbers=[1])
    task = await AiTask.create(task_type=1, status=TaskStatusEnum.running.value, request_params={"novel_id": novel.id})
    service = PromptEditService(novel_id=novel.id, task_id=task.id,
        allowed_targets={('asset', asset.id), ('variant', variant.id), ('scene', scene.id)}, max_batch_size=8)
    return service, scene, asset, variant, task


@pytest.mark.asyncio
async def test_image_and_variant_updates_are_recorded_idempotently_and_undoable():
    service, _, asset, variant, _ = await setup_service()
    edits = [ImagePromptEdit(target_kind=kind, target_id=obj.id, expected_version=prompt_version(obj), prompt=text)
             for kind, obj, text in [('asset', asset, '灰色风衣，柔和光线'), ('variant', variant, '雨夜风衣，冷光')]]
    change = await service.update_image_prompt(edits, tool_call_id="image-1")
    repeated = await service.update_image_prompt(edits, tool_call_id="image-1")
    assert repeated.id == change.id
    assert change.changes[1]['asset_id'] == asset.id
    assert change.changes[0]['target_label'] == asset.canonical_name
    assert change.changes[1]['target_label'] == f'{asset.canonical_name} · {variant.name}'
    assert await PromptChange.all().count() == 1
    await asset.refresh_from_db(); await variant.refresh_from_db()
    assert asset.base_traits == '灰色风衣，柔和光线'
    assert asset.main_image == 'keep.png'
    assert variant.chapter_numbers == [1]
    await service.undo(change.id)
    await service.undo(change.id)
    await asset.refresh_from_db(); await variant.refresh_from_db()
    assert asset.base_traits == '灰色风衣' and variant.base_traits == '雨夜风衣'


@pytest.mark.asyncio
async def test_old_version_and_out_of_scope_target_do_not_write():
    service, scene, asset, _, _ = await setup_service()
    stale = prompt_version(asset)
    asset.base_traits = '用户刚改成黑色'
    await asset.save()
    with pytest.raises(PromptEditConflict):
        await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=stale, prompt='不应保存')], tool_call_id='stale')
    service.allowed_targets = {('scene', scene.id)}
    with pytest.raises(ValueError, match='范围'):
        await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=prompt_version(asset), prompt='不应保存')], tool_call_id='scope')
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
async def test_internal_writer_rejects_a_missing_server_version():
    service, _, asset, _, _ = await setup_service()
    with pytest.raises(ValueError, match='服务端并发版本'):
        await service.update_image_prompt([
            ImagePromptEdit(target_kind='asset', target_id=asset.id, prompt='不应保存')
        ], tool_call_id='missing-version')
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣'


@pytest.mark.asyncio
async def test_batch_conflict_rolls_back_all_targets():
    service, _, asset, variant, _ = await setup_service()
    with pytest.raises(PromptEditConflict):
        await service.update_image_prompt([
            ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=prompt_version(asset), prompt='应回滚'),
            ImagePromptEdit(target_kind='variant', target_id=variant.id, expected_version='stale', prompt='不会提交'),
        ], tool_call_id='batch')
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣'
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
async def test_scene_edit_uses_shared_preparation_and_preserves_metadata():
    service, scene, _, _, _ = await setup_service()
    change = await service.update_storyboard_prompt([
        StoryboardPromptEdit(scene_id=scene.id, expected_version=prompt_version(scene), legacy_prompt='夜晚空站台，暖光从左侧照入。'),
    ], tool_call_id='scene-1')
    await scene.refresh_from_db()
    assert '暖光从左侧照入' in scene.prompt
    assert change.changes[0]['target_label'] == '第 1 章 · 分镜 5'
    assert scene.sequence == 5 and scene.duration == 6 and scene.metadata == {"keep": "metadata"}
    await service.undo(change.id)
    await scene.refresh_from_db()
    assert scene.prompt == '空站台'


@pytest.mark.asyncio
async def test_undo_does_not_overwrite_later_edits():
    service, _, asset, _, _ = await setup_service()
    change = await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=prompt_version(asset), prompt='新提示词')], tool_call_id='image-1')
    await asset.refresh_from_db()
    asset.base_traits = '后续手工修改'
    await asset.save()
    with pytest.raises(PromptEditConflict):
        await service.undo(change.id)
    await asset.refresh_from_db()
    assert asset.base_traits == '后续手工修改'


@pytest.mark.asyncio
async def test_undo_preserves_later_non_prompt_changes():
    service, scene, _, _, _ = await setup_service()
    change = await service.update_storyboard_prompt([
        StoryboardPromptEdit(scene_id=scene.id, expected_version=prompt_version(scene), legacy_prompt='空站台，柔和暖光。'),
    ], tool_call_id='undo-after-metadata')
    await scene.refresh_from_db()
    scene.metadata = {'video_resolution': '1080p'}
    await scene.save()
    await service.undo(change.id)
    await scene.refresh_from_db()
    assert scene.prompt == '空站台'
    assert scene.metadata == {'video_resolution': '1080p'}


@pytest.mark.asyncio
async def test_parallel_duplicate_call_has_one_database_effect():
    service, _, asset, _, _ = await setup_service()
    edits = [ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=prompt_version(asset), prompt='新提示词')]
    changes = await asyncio.gather(*(service.update_image_prompt(edits, tool_call_id='same') for _ in range(2)))
    assert changes[0].id == changes[1].id
    assert await PromptChange.all().count() == 1


@pytest.mark.asyncio
async def test_cancelled_run_and_changed_idempotency_payload_are_rejected():
    service, _, asset, _, task = await setup_service()
    edit = ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=prompt_version(asset), prompt='新提示词')
    await service.update_image_prompt([edit], tool_call_id='same')
    with pytest.raises(PromptEditConflict):
        await service.update_image_prompt([edit.model_copy(update={'prompt': '不同请求'})], tool_call_id='same')
    await asset.refresh_from_db()
    task.status = TaskStatusEnum.cancelled.value
    await task.save()
    with pytest.raises(PromptEditConflict, match='停止|结束'):
        await service.update_image_prompt([edit.model_copy(update={'expected_version': prompt_version(asset)})], tool_call_id='later')


@pytest.mark.asyncio
async def test_safe_schema_creation_twice_keeps_existing_changes():
    from tortoise import Tortoise
    service, _, asset, _, _ = await setup_service()
    await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=prompt_version(asset), prompt='新提示词')], tool_call_id='same')
    for _ in range(2):
        await Tortoise.generate_schemas(safe=True)
    assert await PromptChange.all().count() == 1
    await asset.refresh_from_db()
    assert asset.base_traits == '新提示词'


@pytest.mark.asyncio
async def test_version_and_cas_work_for_utc_timestamps_reloaded_in_local_timezone():
    from datetime import datetime, timezone
    service, _, asset, _, _ = await setup_service()
    timestamp = datetime.now(timezone.utc)
    await Asset.filter(id=asset.id).update(updated_at=timestamp)
    asset.updated_at = timestamp
    version = prompt_version(asset)
    await asset.refresh_from_db()
    assert prompt_version(asset) == version
    change = await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id, expected_version=version, prompt='UTC 新提示词')], tool_call_id='utc')
    await service.undo(change.id)
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣'


@pytest.mark.asyncio
async def test_empty_image_prompt_can_be_filled_after_queryset_update():
    service, _, asset, _, _ = await setup_service()
    await Asset.filter(id=asset.id).update(base_traits=None)
    current = next(target for target in await service.read_targets() if target['kind'] == 'asset')

    change = await service.update_image_prompt([
        ImagePromptEdit(
            target_kind='asset',
            target_id=asset.id,
            expected_version=current['version'],
            prompt='黑色齐肩短发，灰色风衣',
        )
    ], tool_call_id='fill-empty')

    await asset.refresh_from_db()
    assert change.changes[0]['before'] == {'base_traits': None}
    assert asset.base_traits == '黑色齐肩短发，灰色风衣'


@pytest.mark.asyncio
async def test_context_uses_same_selected_visual_variant_as_video_generation():
    service, scene, asset, variant, _ = await setup_service()
    await scene.assets.add(asset)
    scene.metadata = {'asset_variant_ids': {str(asset.id): variant.id}}
    await scene.save()
    targets = await service.read_targets()
    current = next(target for target in targets if target['kind'] == 'scene')
    assert current['entities'][0]['description'] == '雨夜风衣'
    assert f'女主#{variant.name}' in current['entities'][0]['aliases']
    assert current['version'] == prompt_version(scene)


@pytest.mark.asyncio
async def test_scene_context_includes_visual_traits_even_when_story_description_exists():
    service, scene, asset, variant, _ = await setup_service()
    await scene.assets.add(asset)
    variant.description = '故事中的来访者'
    await variant.save()
    targets = await service.read_targets(for_model=True)
    current = next(target for target in targets if target['kind'] == 'scene')
    assert '雨夜风衣' in current['entities'][0]['description']
    assert '故事中的来访者' in current['entities'][0]['description']


@pytest.mark.asyncio
async def test_variant_context_includes_base_identity_without_granting_base_write_scope():
    service, _, asset, variant, _ = await setup_service()
    targets = await service.read_targets()
    current = next(target for target in targets if target['kind'] == 'variant')
    assert current['name'] == '雨夜'
    assert current['base_asset'] == {'id': asset.id, 'name': '女主', 'prompt': '灰色风衣', 'description': None}
    service.allowed_targets = {('variant', variant.id)}
    with pytest.raises(ValueError, match='范围'):
        await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id,
            expected_version=prompt_version(asset), prompt='不能修改基础资产')], tool_call_id='scope-base')


@pytest.mark.asyncio
async def test_image_prompt_preserves_existing_references_without_adding_new_ones():
    service, _, asset, _, _ = await setup_service()
    asset.base_traits = '使用@{参考图1}，灰色风衣'
    await asset.save()
    await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id,
        expected_version=prompt_version(asset), prompt='使用@{参考图1}，灰色风衣，柔和光线')], tool_call_id='ref-1')
    await asset.refresh_from_db()
    with pytest.raises(ValueError, match='素材引用'):
        await service.update_image_prompt([ImagePromptEdit(target_kind='asset', target_id=asset.id,
            expected_version=prompt_version(asset), prompt='使用@{参考图2}，灰色风衣')], tool_call_id='ref-2')


@pytest.mark.asyncio
async def test_image_prompt_rejects_malformed_reference_markup():
    service, _, asset, _, _ = await setup_service()
    with pytest.raises(ValueError, match='素材引用格式'):
        await service.update_image_prompt([
            ImagePromptEdit(
                target_kind='asset',
                target_id=asset.id,
                expected_version=prompt_version(asset),
                prompt='使用@@参考图@，灰色风衣',
            )
        ], tool_call_id='bad-reference')
