"""Storyboard input guards distinguish design edits from image bookkeeping."""
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
async def test_storyboard_keeps_valid_inputs_when_only_asset_image_changes():
    asset, params = await storyboard_plan()
    await validate_step_inputs(params)
    asset.main_image = '/media/new.png'
    asset.metadata = {'image_gallery': ['/media/new.png']}
    await asset.save()
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
async def test_storyboard_detects_new_variant_after_input_snapshot():
    asset, params = await storyboard_plan()
    await AssetVariant.create(asset=asset, name='战斗形态', base_traits='铠甲', chapter_numbers=[1])
    with pytest.raises(ValueError, match='新修改'):
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
async def test_changed_inputs_fail_before_model_request():
    from unittest.mock import patch, AsyncMock
    from services.storyboard.handler import StoryboardTaskHandler
    asset, params = await storyboard_plan()
    asset.description = '新的设定'
    await asset.save()
    with patch('services.storyboard.handler.generate_storyboard', new_callable=AsyncMock) as generate:
        with pytest.raises(ValueError, match='新修改'):
            await StoryboardTaskHandler().execute({**params, 'base_url': 'https://example.invalid',
                'api_key': 'test', 'model': 'test'})
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_dependency_design_snapshot_survives_media_update_but_not_design_edit():
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
    asset.main_image = '/media/new.png'
    await asset.save()
    await validate_step_inputs(params)
    asset.base_traits = '后续人工修改'
    await asset.save()
    with pytest.raises(ValueError, match='新修改'):
        await validate_step_inputs(params)
