import pytest
import asyncio

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.scene import Scene
from models.creation_agent import PromptChange
from schemas.creation_agent import AgentRunRequest, AgentTarget
from schemas.creation_objects import CreationChangeSet
from services.creation_agent.changes import CreationChanges
from test.test_services.test_creation_agent_tools import setup_service


async def crud(scope='chapter', targets=None):
    legacy, scene, asset, variant, task = await setup_service()
    await scene.fetch_related('chapter')
    asset.source_chapters = [scene.chapter.number]
    asset.is_global = False
    await asset.save()
    request = AgentRunRequest(request_id=task.id, message='本章创作验收', chapter_id=scene.chapter_id,
                              write_scope=scope, targets=targets or [])
    service = CreationChanges(novel_id=legacy.novel_id, task_id=task.id, request=request, max_batch_size=8)
    await service.read([AgentTarget(kind='scene', id=scene.id), AgentTarget(kind='asset', id=asset.id)])
    await service.read_creation_context(scene.chapter_id)
    return service, scene, asset, variant, task


@pytest.mark.asyncio
async def test_create_dependent_asset_scene_is_atomic_idempotent_and_undoable():
    service, scene, _, _, _ = await crud()
    changes = CreationChangeSet.model_validate({'operations': [
        {'operation': 'create_setting', 'client_ref': 'coat', 'name': '蓝色雨衣', 'asset_type': 3,
         'description': '蓝色长款雨衣', 'prompt': '蓝色长款雨衣，完整展示材质与轮廓'},
        {'operation': 'create_scene', 'client_ref': 'rain', 'after': scene.id, 'description': '雨衣特写',
         'duration': 3, 'assets': ['coat'], 'prompt': '@{蓝色雨衣}挂在衣架上，细雨从窗外落下。'},
    ]})
    saved = await service.apply(changes, tool_call_id='create')
    repeated = await service.apply(changes, tool_call_id='create')
    assert repeated.id == saved.id
    assert [item['operation'] for item in saved.changes] == ['create', 'create']
    new_scene = await Scene.get(id=saved.changes[1]['target_id'])
    new_asset = await Asset.get(id=saved.changes[0]['target_id'])
    assert new_asset.id in await new_scene.assets.all().values_list('id', flat=True)
    assert '蓝色长款雨衣' in new_scene.prompt
    await service.undo(saved.id)
    assert not await Scene.filter(id=new_scene.id).exists()
    assert not await Asset.filter(id=new_asset.id).exists()
    assert await Scene.filter(id=scene.id).exists()


@pytest.mark.asyncio
async def test_dependent_failure_does_not_leave_new_asset():
    service, scene, _, _, _ = await crud()
    batch = CreationChangeSet.model_validate({'operations': [
        {'operation': 'create_setting', 'client_ref': 'coat', 'name': '蓝色雨衣', 'asset_type': 3,
         'description': '雨衣', 'prompt': '蓝色雨衣'},
        {'operation': 'create_scene', 'client_ref': 'rain', 'duration': 3, 'assets': ['missing'],
         'description': '雨衣特写', 'prompt': '完整画面'},
    ]})
    with pytest.raises(ValueError):
        await service.apply(batch, tool_call_id='bad')
    assert not await Asset.filter(canonical_name='蓝色雨衣').exists()
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
async def test_updates_and_delete_restore_preserve_later_nonedited_fields():
    service, scene, asset, _, _ = await crud()
    batch = CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'description': '新的描述', 'prompt': '灰色风衣，暖光'}}]})
    saved = await service.apply(batch, tool_call_id='update')
    await Asset.filter(id=asset.id).update(main_image='later.png')
    await service.undo(saved.id)
    await asset.refresh_from_db()
    assert asset.base_traits == '灰色风衣' and asset.main_image == 'later.png'
    await service.read([AgentTarget(kind='scene', id=scene.id)])
    deleted = await service.apply(CreationChangeSet.model_validate({'operations': [
        {'operation': 'delete', 'target': {'kind': 'scene', 'id': scene.id}}]}), tool_call_id='delete')
    assert not await Scene.filter(id=scene.id).exists()
    await service.undo(deleted.id)
    assert await Scene.filter(id=scene.id).exists()


@pytest.mark.asyncio
async def test_read_only_selected_scope_and_concurrent_edit_cannot_write():
    service, scene, asset, _, task = await crud('read_only')
    batch = CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'prompt': '错误修改'}}]})
    with pytest.raises(ValueError, match='只读'):
        await service.apply(batch, tool_call_id='readonly')
    service = CreationChanges(novel_id=service.novel_id, task_id=task.id,
        request=service.request.model_copy(update={'write_scope': 'selected'}), max_batch_size=8)
    await service.read([AgentTarget(kind='asset', id=asset.id)])
    with pytest.raises(ValueError, match='指定'):
        await service.apply(batch, tool_call_id='empty-selection')
    service = CreationChanges(novel_id=service.novel_id, task_id=task.id,
        request=service.request.model_copy(update={'write_scope': 'chapter'}), max_batch_size=8)
    await service.read([AgentTarget(kind='asset', id=asset.id)])
    await Asset.filter(id=asset.id).update(base_traits='用户最新手工修改')
    with pytest.raises(ValueError, match='重新读取|变化'):
        await service.apply(batch, tool_call_id='stale')
    await service.read([AgentTarget(kind='asset', id=asset.id)])
    await type(task).filter(id=task.id).update(status=5)
    with pytest.raises(ValueError, match='停止|结束'):
        await service.apply(batch, tool_call_id='stopped')


@pytest.mark.asyncio
async def test_multiple_insertions_and_undo_are_one_consistent_change_set():
    service, scene, _, _, _ = await crud()
    batch = CreationChangeSet.model_validate({'operations': [
        {'operation': 'create_scene', 'client_ref': 'one', 'after': scene.id,
         'description': '第一幅空镜', 'duration': 3, 'prompt': '雨夜空荡的站台。'},
        {'operation': 'create_scene', 'client_ref': 'two', 'after': 'one',
         'description': '第二幅空镜', 'duration': 3, 'prompt': '站台水洼中的暖色倒影。'},
    ]})
    saved = await service.apply(batch, tool_call_id='two')
    await service.undo(saved.id)
    assert await Scene.filter(chapter_id=scene.chapter_id).values_list('id', flat=True) == [scene.id]


@pytest.mark.asyncio
async def test_chapter_scope_cannot_change_shared_identity_or_other_chapter():
    service, scene, asset, _, _ = await crud()
    second = await Chapter.create(novel_id=service.novel_id, number=2, name='清晨', content='第二章')
    other_scene = await Scene.create(chapter=second, sequence=1, prompt='清晨阳光', duration=3)
    await other_scene.assets.add(asset)
    await service.read([AgentTarget(kind='asset', id=asset.id), AgentTarget(kind='scene', id=other_scene.id)])
    batch = CreationChangeSet.model_validate({'operations': [{'operation': 'update_setting',
        'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'prompt': '蓝色雨衣'}}]})
    with pytest.raises(ValueError, match='跨章共享'):
        await service.apply(batch, tool_call_id='shared')
    with pytest.raises(ValueError, match='章节范围'):
        await service.apply(CreationChangeSet.model_validate({'operations': [
            {'operation': 'delete', 'target': {'kind': 'scene', 'id': other_scene.id}}]}), tool_call_id='other-chapter')
    assert await PromptChange.all().count() == 0


@pytest.mark.asyncio
async def test_duration_edit_rejects_unsynchronized_legacy_timeline():
    service, scene, _, _, _ = await crud()
    await Scene.filter(id=scene.id).update(prompt='0s-6s: 雨落在空站台。')
    await service.read([AgentTarget(kind='scene', id=scene.id)])
    batch = CreationChangeSet.model_validate({'operations': [
        {'operation': 'update_scene', 'scene_id': scene.id, 'fields': {'duration': 3}}]})
    with pytest.raises(ValueError, match='时间轴'):
        await service.apply(batch, tool_call_id='duration')
    assert (await Scene.get(id=scene.id)).duration == 6
    batch.operations[0].fields = type(batch.operations[0].fields)(duration=3, prompt='0s-3s: 雨落在空站台。')
    saved = await service.apply(batch, tool_call_id='duration-corrected')
    assert saved.changes[0]['after']['duration'] == 3


@pytest.mark.asyncio
async def test_new_setting_cannot_be_undone_after_later_references():
    service, scene, _, _, _ = await crud()
    saved = await service.apply(CreationChangeSet.model_validate({'operations': [
        {'operation': 'create_setting', 'client_ref': 'coat', 'asset_type': 3, 'name': '蓝色雨衣', 'description': '雨衣', 'prompt': '完整的蓝色雨衣'}]}), tool_call_id='new-coat')
    asset = await Asset.get(id=saved.changes[0]['target_id'])
    await scene.assets.add(asset)
    with pytest.raises(ValueError, match='引用'):
        await service.undo(saved.id)
    assert await Asset.filter(id=asset.id).exists()


@pytest.mark.asyncio
async def test_details_and_observed_version_are_atomic_with_page_edits(monkeypatch):
    from services.creation_agent.tools import PromptEditService

    service, _, asset, _, _ = await crud()
    projected = asyncio.Event()
    writer_started = asyncio.Event()
    original = PromptEditService.read_targets

    async def delayed_projection(reader, **kwargs):
        result = await original(reader, **kwargs)
        projected.set()
        await writer_started.wait()
        return result

    async def page_write():
        await projected.wait()
        writer_started.set()
        asset.base_traits = '用户新改的蓝色雨衣'
        await asset.save(update_fields=['base_traits', 'updated_at'])

    monkeypatch.setattr(PromptEditService, 'read_targets', delayed_projection)
    details, _ = await asyncio.wait_for(asyncio.gather(
        service.read([AgentTarget(kind='asset', id=asset.id)]), page_write()), timeout=3)
    assert details[0]['prompt'] == '灰色风衣'
    with pytest.raises(ValueError, match='变化'):
        await service.apply(CreationChangeSet.model_validate({'operations': [{
            'operation': 'update_setting', 'target': {'kind': 'asset', 'id': asset.id},
            'fields': {'prompt': '基于旧画面的调整'},
        }]}), tool_call_id='stale-read')
    assert (await Asset.get(id=asset.id)).base_traits == '用户新改的蓝色雨衣'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['scene', 'asset'])
async def test_conversational_undo_obeys_current_scope_status_and_conversation(kind):
    from models.ai_task import AiTask
    from models.creation_agent import AgentConversation, AgentMessage

    service, scene, asset, _, original_task = await crud()
    target = scene if kind == 'scene' else asset
    unrelated = AgentTarget(kind='asset', id=asset.id) if kind == 'scene' else AgentTarget(kind='scene', id=scene.id)
    saved = await service.apply(CreationChangeSet.model_validate({'operations': [
        {'operation': 'delete', 'target': {'kind': kind, 'id': target.id}},
    ]}), tool_call_id='remove')
    conversation = await AgentConversation.create(novel_id=service.novel_id)
    await AgentMessage.create(conversation=conversation, task=original_task, role='user',
        request_id=original_task.id, request_hash='original', run_input=service.request.model_dump(mode='json'))
    task = await AiTask.create(task_type=1, status=2, request_params={'novel_id': service.novel_id})
    source = await AgentMessage.create(conversation=conversation, task=task, role='user', request_id=task.id, request_hash='undo')

    def current(scope='chapter', targets=None):
        return CreationChanges(novel_id=service.novel_id, task_id=task.id,
            request=service.request.model_copy(update={'request_id': task.id, 'write_scope': scope, 'targets': targets or []}), max_batch_size=8)

    with pytest.raises(ValueError, match='只读'):
        await current('read_only').undo_for_run(saved.id, source)
    with pytest.raises(ValueError, match='指定'):
        await current('selected', [unrelated]).undo_for_run(saved.id, source)
    await AiTask.filter(id=task.id).update(status=5)
    with pytest.raises(ValueError, match='停止'):
        await current().undo_for_run(saved.id, source)
    await AiTask.filter(id=task.id).update(status=2)
    other = await AgentConversation.create(novel_id=service.novel_id)
    source.conversation_id = other.id
    with pytest.raises(ValueError, match='本会话'):
        await current().undo_for_run(saved.id, source)
    source.conversation_id = conversation.id
    restored = await current().undo_for_run(saved.id, source)
    assert restored.reverted_at
    assert await type(target).filter(id=target.id).exists()
    assert (await current().undo_for_run(saved.id, source)).id == saved.id


@pytest.mark.asyncio
async def test_chapter_variant_and_structured_scenes_keep_independent_identity_and_numbering():
    import re
    from test.test_services.test_storyboard_handler import _shot

    service, old_scene, asset, _, _ = await crud()
    second = await Chapter.create(novel_id=service.novel_id, number=2, name='咖啡馆', content='晨光')
    await Asset.filter(id=asset.id).update(source_chapters=[1, 2])
    other = await Scene.create(chapter=second, sequence=1, prompt='女主穿灰色风衣。', duration=3)
    await other.assets.add(asset)
    # Existing chapter-one variant is edited, without changing its parent.
    variant = await AssetVariant.get(asset_id=asset.id)
    await service.read([AgentTarget(kind='asset', id=asset.id), AgentTarget(kind='variant', id=variant.id)])
    await service.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_setting', 'target': {'kind': 'variant', 'id': variant.id},
        'fields': {'name': '蓝雨衣', 'description': '同一人物的雨衣形态', 'prompt': '女主齐肩黑发，穿深蓝色长款连帽雨衣。'},
    }]}), tool_call_id='costume')
    await service.read_creation_context(old_scene.chapter_id)
    shot = _shot(1, '@{女主}站在雨夜站台。').model_dump()
    shot.update(duration='3s', actions=['0s-3s: @{女主}看向远处。'], segments=[{
        'duration': 1, 'description': '站台人物', 'shot_size_and_camera': '中景',
        'visual_prose': '@{女主}站在站台，面向轨道。', 'actions': ['细雨飘落。'], 'camera_movement': '固定机位',
    } for _ in range(3)])
    saved = await service.apply(CreationChangeSet.model_validate({'operations': [
        {'operation': 'create_scene', 'client_ref': ref, 'duration': 3, 'description': f'{ref}雨夜站台',
         'assets': [asset.id], 'variant_refs': [variant.id], 'structure': shot}
        for ref in ['first', 'second']
    ]}), tool_call_id='two-independent')
    for item in saved.changes:
        created = await Scene.get(id=item['target_id'])
        assert re.findall(r'【镜头(\d+)', created.prompt) == ['1', '2', '3']
        assert '深蓝色长款连帽雨衣' in created.prompt
        assert created.metadata['asset_variant_ids'] == {str(asset.id): variant.id}
    await asset.refresh_from_db(); await other.refresh_from_db()
    assert asset.base_traits == '灰色风衣'
    assert other.prompt == '女主穿灰色风衣。'


@pytest.mark.asyncio
async def test_rename_synchronizes_exact_references_atomically_and_respects_batch_limit():
    service, scene, asset, _, _ = await crud()
    await Scene.filter(id=scene.id).update(prompt='@{女主}站在门口。', description='@{女主}入场')
    await scene.assets.add(asset)
    await service.read([AgentTarget(kind='asset', id=asset.id), AgentTarget(kind='scene', id=scene.id)])
    batch = CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_setting', 'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'name': '林夏'},
    }]})
    service.max_batch_size = 1
    with pytest.raises(ValueError, match='上限'):
        await service.apply(batch, tool_call_id='too-many')
    assert (await Asset.get(id=asset.id)).canonical_name == '女主'

    assert (await Scene.get(id=scene.id)).prompt == '@{女主}站在门口。'
    service.max_batch_size = 8
    saved = await service.apply(batch, tool_call_id='rename')
    assert len(saved.changes) == 2
    assert (await Scene.get(id=scene.id)).prompt == '@{林夏}站在门口。'
    assert '女主' in (await Asset.get(id=asset.id)).aliases
    await service.undo(saved.id)
    assert (await Scene.get(id=scene.id)).prompt == '@{女主}站在门口。'
    assert (await Asset.get(id=asset.id)).canonical_name == '女主'

@pytest.mark.asyncio
async def test_new_variant_schema_and_creation_preserve_parent_identity():
    service, scene, asset, _, _ = await crud()
    second = await Chapter.create(novel_id=service.novel_id, number=2, name='咖啡馆', content='清晨')
    service.request.chapter_id = second.id
    service.scope.request.chapter_id = second.id
    await service.read_creation_context(second.id)
    batch = CreationChangeSet.model_validate({'operations': [{
        'operation': 'create_setting', 'kind': 'variant', 'client_ref': 'coat',
        'parent': asset.id, 'name': '咖啡馆雨衣', 'description': '本章临时雨衣形态',
        'prompt': '女主齐肩黑发，深蓝色长款连帽雨衣。',
    }]})
    assert 'asset_type' not in CreationChangeSet.model_json_schema()['$defs']['CreateVariantSetting']['properties']
    saved = await service.apply(batch, tool_call_id='variant')
    variant = await AssetVariant.get(id=saved.changes[0]['target_id'])
    assert variant.asset_id == asset.id and variant.chapter_numbers == [2]
    assert (await Asset.get(id=asset.id)).base_traits == '灰色风衣'
    await service.undo(saved.id)
    assert not await AssetVariant.filter(id=variant.id).exists()


@pytest.mark.asyncio
async def test_qualified_reference_renames_preserve_prose_and_reject_running_scenes():
    from models.video import Video

    service, scene, asset, variant, _ = await crud()
    text = '@{女主#雨夜}站在门口，女主望向@{女主同伴}。'
    await Scene.filter(id=scene.id).update(prompt=text, description='@{女主#雨夜}入场')
    await scene.assets.add(asset)
    await service.read([AgentTarget(kind='asset', id=asset.id), AgentTarget(kind='variant', id=variant.id),
                        AgentTarget(kind='scene', id=scene.id)])
    rename = CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_setting', 'target': {'kind': 'variant', 'id': variant.id}, 'fields': {'name': '晨光'},
    }]})
    video = await Video.create(scene=scene, model_type=1, status=2)
    with pytest.raises(ValueError, match='生成任务'):
        await service.apply(rename, tool_call_id='busy-rename')
    assert (await AssetVariant.get(id=variant.id)).name == '雨夜'
    assert (await Scene.get(id=scene.id)).prompt == text
    await Video.filter(id=video.id).update(status=3)
    saved = await service.apply(rename, tool_call_id='variant-rename')
    assert (await Scene.get(id=scene.id)).prompt == text.replace('@{女主#雨夜}', '@{女主#晨光}')
    await service.undo(saved.id)
    await service.read([AgentTarget(kind='asset', id=asset.id), AgentTarget(kind='scene', id=scene.id)])
    await service.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_setting', 'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'name': '林夏'},
    }]}), tool_call_id='parent-rename')
    assert (await Scene.get(id=scene.id)).prompt == text.replace('@{女主#雨夜}', '@{林夏#雨夜}')


@pytest.mark.asyncio
async def test_global_identity_requires_explicit_target_even_with_one_source_chapter():
    service, _, asset, _, _ = await crud()
    await Asset.filter(id=asset.id).update(is_global=True)
    await service.read([AgentTarget(kind='asset', id=asset.id)])
    with pytest.raises(ValueError, match='跨章共享'):
        await service.apply(CreationChangeSet.model_validate({'operations': [{
            'operation': 'update_setting', 'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'prompt': '蓝色雨衣'},
        }]}), tool_call_id='global-base')
    assert (await Asset.get(id=asset.id)).base_traits == '灰色风衣'


@pytest.mark.asyncio
async def test_existing_unsupported_setting_cannot_be_managed_by_discovered_id():
    service, _, _, _, _ = await crud()
    product = await Asset.create(novel_id=service.novel_id, canonical_name='历史商品', asset_type=4)
    variant = await AssetVariant.create(asset=product, name='历史形态')
    for kind, target in [('asset', product), ('variant', variant)]:
        with pytest.raises(ValueError, match='人物、场景、道具'):
            await service.read([AgentTarget(kind=kind, id=target.id)])


@pytest.mark.asyncio
async def test_undo_rename_reports_occupied_name_without_overwriting_either_setting():
    service, _, asset, _, _ = await crud()
    saved = await service.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_setting', 'target': {'kind': 'asset', 'id': asset.id}, 'fields': {'name': '林夏'},
    }]}), tool_call_id='rename')
    later = await Asset.create(novel_id=service.novel_id, canonical_name='女主', asset_type=1)
    with pytest.raises(ValueError, match='原名称或位置'):
        await service.undo(saved.id)
    assert (await Asset.get(id=asset.id)).canonical_name == '林夏'
    assert await Asset.filter(id=later.id, canonical_name='女主').exists()
    assert (await PromptChange.get(id=saved.id)).reverted_at is None
