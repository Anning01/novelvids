"""Targeted omissions cannot be hidden by a completed chapter receipt."""
from test.agent_stream_fixtures import streaming_model

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from controllers.chapter import chapter_controller
from models.agent_operation import AgentOperation
from models.asset import Asset
from models.creation_agent import AgentMessage
from models.usage_record import ModelUsageRecord
from schemas.creation_plan import CreativeRequirement
from services.ai_task_executor import ai_task_executor
from services.creation_agent.direct_plan import prepare_direct_plan
from services.creation_agent.plans import load_plan
from test.test_services.test_asset_design_instructions import fixed_asset_prompt
from test.test_services.test_extraction_reuse import extraction_fixture as base_fixture


async def extraction_fixture():
    result = await base_fixture()
    chapter = result[1]
    chapter.content += '主角拔出玄铁剑，这是他的佩剑，剑身乌黑。'
    await chapter.save()
    return result


async def targeted_run(chapter, snapshot, inventory, *, extra=False, revise=False, before_design=None):
    counts = {'inventory': 0, 'design': 0}
    async def respond(messages, info):
        tool = info.output_tools[0]
        properties = tool.parameters_json_schema['properties']
        if 'characters' in properties:
            counts['inventory'] += 1
            assert 'target_requirements' in str(messages)
            payload = inventory
        elif 'findings' in properties:
            payload = {'plan_followed': True, 'issues': [], 'findings': [
                {'requirement_id': 'sword', 'passed': True, 'location': 'items/玄铁剑', 'detail': '只补剑'}]}
        else:
            counts['design'] += 1
            if before_design:
                await before_design()
            payload = {'persons': [], 'scenes': [], 'items': [
                {'name': '玄铁剑', 'base_traits': fixed_asset_prompt(kind='item', snapshot=snapshot)}]}
            if extra:
                payload['scenes'] = [{'name': '未指定场景', 'base_traits': fixed_asset_prompt(kind='scene', snapshot=snapshot)}]
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)])
    model = streaming_model(respond)
    model.client = AsyncMock()
    async def prepare(task, execution):
        await prepare_direct_plan(task, execution)
        plan = await load_plan(task.id)
        plan.brief.asset_scope = plan.steps[0].asset_scope = 'targeted'
        plan.steps[0].mode = 'revise' if revise else 'fill_missing'
        plan.steps[0].instructions = '主角的剑呢？补上遗漏的剑。'
        plan.brief.requirements = [CreativeRequirement(id='sword', instruction='只补主角的剑',
            source_quote='主角的剑呢', acceptance='核对原文，只补剑', chapter_ids=[chapter.id])]
        plan.steps[0].requirement_ids = ['sword']
        await AgentMessage.filter(id=plan.source_message_id).update(content=plan.steps[0].instructions)
        await AgentOperation.filter(task=task, key='creation:plan').update(result=plan.model_dump(mode='json'))
    with patch('services.creation_agent.handler.configured_model', return_value=model), patch(
        'services.creation_agent.direct_plan.prepare_direct_plan', side_effect=prepare):
        task = await chapter_controller.extract(chapter.id)
        task.request_params['skill_snapshot'] = snapshot.model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    return task, counts


def sword_inventory(chapter, name='玄铁剑', presence='present'):
    return {'characters': [], 'scenes': [], 'items': [
        {'name': name, 'presence': presence, 'quote': chapter.content}]}


@pytest.mark.asyncio
async def test_targeted_omission_bypasses_complete_chapter_and_repeat_keeps_existing_design():
    novel, chapter, snapshot, _, _, run = await extraction_fixture()
    await run()
    before = {row.id: (row.base_traits, row.main_image) for row in await Asset.filter(novel=novel)}
    task, counts = await targeted_run(chapter, snapshot, sword_inventory(chapter))
    assert task.status == 3, task.error_message
    assert counts == {'inventory': 1, 'design': 1}
    assert len(task.response_data['asset_ids']) == 1
    sword = await Asset.get(novel=novel, asset_type=3, canonical_name='玄铁剑')
    assert sword.source_chapters == [chapter.number]
    assert {row.id: (row.base_traits, row.main_image) for row in await Asset.filter(id__in=before)} == before
    usage = await ModelUsageRecord.all().count()
    task, counts = await targeted_run(chapter, snapshot, sword_inventory(chapter))
    assert task.status == 3, task.error_message
    assert counts == {'inventory': 0, 'design': 0}
    assert await ModelUsageRecord.all().count() == usage
    assert await Asset.filter(novel=novel, asset_type=3, canonical_name='玄铁剑').count() == 1


@pytest.mark.asyncio
async def test_targeted_deleted_asset_is_not_silently_restored():
    from datetime import datetime, timezone
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    sword = await Asset.create(novel=novel, asset_type=3, canonical_name='玄铁剑', base_traits='已删除')
    await Asset.filter(id=sword.id).update(deleted_at=datetime.now(timezone.utc))
    task, counts = await targeted_run(chapter, snapshot, sword_inventory(chapter))
    assert task.status == 4 and counts['design'] == 0
    assert await Asset.filter(novel=novel).count() == 0


@pytest.mark.asyncio
async def test_targeted_repair_does_not_overwrite_a_concurrent_user_edit():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    sword = await Asset.create(novel=novel, asset_type=3, canonical_name='玄铁剑', base_traits='')
    async def user_edit():
        await Asset.filter(id=sword.id).update(base_traits='用户刚刚手改的剑')
    task, _ = await targeted_run(chapter, snapshot, sword_inventory(chapter), before_design=user_edit)
    assert task.status == 4
    await sword.refresh_from_db()
    assert sword.base_traits == '用户刚刚手改的剑'


@pytest.mark.asyncio
async def test_targeted_inventory_rejects_fabricated_source_quote_before_design():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    inventory = sword_inventory(chapter)
    inventory['items'][0]['quote'] = '原文根本没有的句子'
    task, counts = await targeted_run(chapter, snapshot, inventory)
    assert task.status == 4 and counts['design'] == 0
    assert await Asset.filter(novel=novel).count() == 0


def test_legacy_plans_default_to_complete_chapter_scope():
    from schemas.creation_plan import CreationBrief, CreationPlanStep
    assert CreationBrief.model_validate({}).asset_scope == 'chapter'
    step = CreationPlanStep.model_validate({'id': 'old', 'operation': 'assets', 'target_id': 1,
        'instructions': '整章提取', 'label': '资产'})
    assert step.asset_scope == 'chapter'


@pytest.mark.asyncio
async def test_targeted_existing_alias_adds_association_without_design_call():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    sword = await Asset.create(novel=novel, asset_type=3, canonical_name='玄铁剑', aliases=['主角佩剑'],
        base_traits=fixed_asset_prompt(kind='item', snapshot=snapshot), main_image='/media/keep.png', source_chapters=[99])
    await Asset.create(novel=novel, asset_type=2, canonical_name='玄铁剑', base_traits='同名场景不应修改')
    task, counts = await targeted_run(chapter, snapshot, sword_inventory(chapter, name='主角佩剑', presence='mentioned'))
    assert task.status == 3, task.error_message
    assert counts == {'inventory': 1, 'design': 0}
    await sword.refresh_from_db()
    assert sword.source_chapters == sorted([chapter.number, 99]) and sword.main_image == '/media/keep.png'
    assert (await Asset.get(novel=novel, asset_type=2)).base_traits == '同名场景不应修改'


@pytest.mark.asyncio
async def test_targeted_absent_source_does_not_design_or_create_assets():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    task, counts = await targeted_run(chapter, snapshot, {'characters': [], 'scenes': [], 'items': []})
    assert task.status == 3, task.error_message
    assert counts == {'inventory': 1, 'design': 0}
    assert '未找到指定资产' in task.response_data['not_applied_reason']
    assert await Asset.filter(novel=novel).count() == 0
    assert '未找到指定资产' in (await AgentMessage.get(task=task, role='assistant')).content


@pytest.mark.asyncio
async def test_targeted_unrequested_outputs_are_never_persisted():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    task, _ = await targeted_run(chapter, snapshot, sword_inventory(chapter), extra=True)
    assert task.status == 4
    assert await Asset.filter(novel=novel).count() == 0


@pytest.mark.asyncio
async def test_targeted_empty_design_is_repaired_without_touching_other_assets():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    sword = await Asset.create(novel=novel, asset_type=3, canonical_name='玄铁剑', base_traits='', main_image='/media/keep.png')
    task, counts = await targeted_run(chapter, snapshot, sword_inventory(chapter))
    assert task.status == 3, task.error_message
    await sword.refresh_from_db()
    assert counts == {'inventory': 1, 'design': 1}
    assert sword.base_traits and sword.main_image == '/media/keep.png'


@pytest.mark.asyncio
async def test_targeted_revise_does_not_silently_reuse_existing_design():
    novel, chapter, snapshot, _, _, _ = await extraction_fixture()
    await Asset.create(novel=novel, asset_type=3, canonical_name='玄铁剑', base_traits=fixed_asset_prompt(kind='item', snapshot=snapshot))
    task, counts = await targeted_run(chapter, snapshot, sword_inventory(chapter), revise=True)
    assert task.status == 3, task.error_message
    assert counts == {'inventory': 1, 'design': 1}


@pytest.mark.asyncio
async def test_targeted_plan_reads_source_even_when_chapter_has_complete_receipt():
    from types import SimpleNamespace
    from schemas.creation_plan import CreationBrief, CreationPlanDraft, CreationPlanStep, SourceReading
    from services.creation_agent.plans import CreationPlanner
    from services.extraction.reuse import extraction_reuse
    from test.test_services.test_creation_plans import plan_fixture
    _, request, chapters, _, source, execution = await plan_fixture()
    chapter = chapters[0]
    message = '主角的剑呢？补上遗漏的剑。'
    source.content = message
    await source.save()
    request = request.model_copy(update={'message': message})
    calls = []
    async def generate(skill, facts, output_type, **options):
        calls.append(skill)
        if skill == 'planning_request':
            return CreationBrief(operations=['assets'], asset_scope='targeted', asset_chapter_ids=[chapter.id],
                requirements=[CreativeRequirement(id='sword', instruction=message, source_quote=message,
                    acceptance='只补剑', chapter_ids=[chapter.id])])
        if skill == 'source_reading':
            return SourceReading(summary='核对本章是否有剑', candidates=[])
        return CreationPlanDraft(summary='仅核对补全剑', steps=[CreationPlanStep(id='sword', operation='assets',
            target_id=chapter.id, requirement_ids=['sword'], instructions=message, label='补漏')])
    with patch.object(execution, 'generate', side_effect=generate), patch.object(extraction_reuse, 'find',
        AsyncMock(return_value=SimpleNamespace(complete=True))) as reuse:
        plan = await CreationPlanner(execution, source).prepare(request)
    reuse.assert_not_called()
    assert calls == ['planning_request', 'source_reading', 'creation_planning']
    assert plan.steps[0].asset_scope == 'targeted'


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_targeted_prompt_contracts(language):
    from prompts.creation_plan import asset_request_instructions
    from prompts.extraction import targeted_cast_instructions, targeted_design_instructions
    assert 'targeted' in asset_request_instructions(language)
    assert 'target_requirements' in targeted_cast_instructions(language)
    assert 'required_asset_names' in targeted_design_instructions(language)
