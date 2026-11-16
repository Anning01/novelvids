"""Rollback preserves v1.9 object guards and reads newer saved plan payloads."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.creation_agent import AgentMessage
from services.creation_agent.direct_plan import prepare_direct_plan
from services.creation_agent.step_context import validate_step_inputs
from test.test_services.test_creation_plans import confirmed_fixture


async def storyboard_plan():
    conversation, _, plan, _, execution = await confirmed_fixture()
    chapter_id = plan.steps[0].target_id
    from models.chapter import Chapter
    chapter = await Chapter.get(id=chapter_id)
    asset = await Asset.create(novel_id=plan.novel_id, asset_type=1, canonical_name='主角',
        base_traits='灰衣', source_chapters=[chapter.number])
    task = await AiTask.create(task_type=3, status=2, request_params={})
    await AgentMessage.create(conversation_id=conversation.id, task=task, role='user',
        request_id=uuid4(), request_hash='storyboard-input', content='生成分镜', run_input={})
    params = {'task_id': str(task.id), 'novel_id': plan.novel_id, 'chapter_id': chapter_id}
    await prepare_direct_plan(task, SimpleNamespace(params=params))
    return asset, params


@pytest.mark.asyncio
async def test_v19_storyboard_keeps_original_strict_object_version_guard():
    asset, params = await storyboard_plan()
    await validate_step_inputs(params)
    asset.main_image = '/media/new.png'
    asset.metadata = {'image_gallery': ['/media/new.png']}
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [('base_traits', '红衣'), ('canonical_name', '新名字'), ('source_chapters', [])])
async def test_storyboard_still_rejects_changed_design_inputs(field, value):
    asset, params = await storyboard_plan()
    setattr(asset, field, value)
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)


@pytest.mark.asyncio
async def test_v19_base_snapshot_is_not_replaced_by_a_variant_collection_fingerprint():
    asset, params = await storyboard_plan()
    await AssetVariant.create(asset=asset, name='战斗形态', base_traits='铠甲', chapter_numbers=[1])
    await validate_step_inputs(params)


@pytest.mark.asyncio
async def test_legacy_plan_keeps_strict_conflict_detection():
    from models.agent_operation import AgentOperation
    asset, params = await storyboard_plan()
    row = await AgentOperation.get(task_id=params['creation_plan_id'], key='creation:plan')
    row.result.pop('storyboard_input_versions')
    await row.save(update_fields=['result'])
    asset.main_image = '/media/new.png'
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)


@pytest.mark.asyncio
async def test_v19_save_guard_still_protects_changed_inputs_and_existing_scenes():
    from models.scene import Scene
    from schemas.agent_workflow import StructuredSkillStoryboard
    from services.creation_agent.skill_execution import current_execution
    from services.storyboard.handler import StoryboardTaskHandler
    from test.test_services.test_storyboard_speech_timing import snapshot
    from test.test_services.test_storyboard_partial_repair import raw_shot
    asset, params = await storyboard_plan()
    asset.description = '新的设定'
    await asset.save()
    count = await Scene.filter(chapter_id=params['chapter_id']).count()
    from services.storyboard.validation import prepare_skill_storyboard
    frozen = snapshot()
    storyboard = prepare_skill_storyboard(StructuredSkillStoryboard(shots=[raw_shot(1)]), frozen, 'zh', [], 'cinematic')
    token = current_execution.set(SimpleNamespace(params=params, snapshot=frozen))
    try:
        with pytest.raises(ValueError, match='新修改'):
            await StoryboardTaskHandler()._save_scenes(params['chapter_id'],
                storyboard, {}, 0, entities=[])
    finally:
        current_execution.reset(token)
    assert await Scene.filter(chapter_id=params['chapter_id']).count() == count


@pytest.mark.asyncio
async def test_v19_dependency_receipts_keep_original_object_versions():
    from models.agent_operation import AgentOperation
    from schemas.creation_plan import CreationPlanStep
    from services.creation_agent.input_versions import storyboard_input_versions
    from services.creation_agent.object_state import object_version
    asset, params = await storyboard_plan()
    row = await AgentOperation.get(task_id=params['creation_plan_id'], key='creation:plan')
    row.result['steps'][0]['depends_on'] = ['design']
    row.result['steps'].insert(0, CreationPlanStep(id='design', operation='assets', target_id=params['chapter_id'],
        label='设定', instructions='生成设定', mode='fill_missing').model_dump(mode='json'))
    await row.save(update_fields=['result'])
    asset.base_traits = '已批准的新设定'
    await asset.save()
    versions = {f'asset:{asset.id}': await object_version(asset)}
    await AgentOperation.create(task_id=params['creation_run_id'], key='plan-step:design', state='completed',
        result={'status': 'completed', 'object_versions': versions,
                'storyboard_input_versions': await storyboard_input_versions(versions)})
    await validate_step_inputs(params)
    asset.main_image = '/media/new.png'
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)
    asset.base_traits = '后续人工修改'
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)
