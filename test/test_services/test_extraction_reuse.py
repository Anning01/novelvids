from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from controllers.chapter import chapter_controller
from models.ai_task import AiTask
from models.asset import Asset
from models.config import GeneralConfig
from models.usage_record import ModelUsageRecord
from services.ai_task_executor import ai_task_executor
from services.extraction.reuse import extraction_reuse
from test.test_services.test_asset_design_instructions import synthetic_snapshot, fixed_asset_prompt
from test.test_services.test_skill_workflow import enabled_project


async def extraction_fixture(with_variant=False, repair_hook=None):
    novel, chapter, config = await enabled_project()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': 'zh'})
    config.pricing = {'type': 'text', 'currency': 'CNY', 'input_price_per_1m': 1, 'output_price_per_1m': 2}
    await config.save()
    snapshot = synthetic_snapshot()
    counts = {'inventory': 0, 'design': 0}
    requested = []

    async def respond(messages, info):
        tool = info.output_tools[0]
        if 'characters' in tool.parameters_json_schema['properties']:
            counts['inventory'] += 1
            entry = lambda name: {'name': name, 'presence': 'present', 'quote': chapter.content}
            payload = {'characters': [entry('角色甲')], 'scenes': [entry('地点甲')], 'items': [entry('道具甲')]}
        else:
            counts['design'] += 1
            if counts['design'] > 1 and repair_hook:
                await repair_hook()
            requested.append(str(messages) + info.instructions)
            fields = [('persons', 'person', '角色甲'), ('scenes', 'scene', '地点甲'), ('items', 'item', '道具甲')]
            payload = {field: [{'name': name, 'base_traits': fixed_asset_prompt(kind=kind, snapshot=snapshot)}]
                       for field, kind, name in fields}
            if with_variant:
                payload['persons'][0]['variant'] = {'name': '新外形', 'description': '本章形态',
                    'base_traits': fixed_asset_prompt(snapshot=snapshot), 'change_reason': '本章明确出现稳定外形变化'}
            if 'issues_to_fix' in info.instructions:
                missing = 'persons' if '人物/角色甲' in info.instructions else 'items'
                payload = {field: items if field == missing else [] for field, items in payload.items()}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)], usage=RequestUsage(input_tokens=100, output_tokens=20))

    model = FunctionModel(respond)
    model.client = AsyncMock()

    async def run(expect_success=True):
        with patch('services.creation_agent.handler.configured_model', return_value=model):
            task = await chapter_controller.extract(chapter.id)
            task.request_params['skill_snapshot'] = snapshot.model_dump()
            await task.save()
            await ai_task_executor.run(task)
        await task.refresh_from_db()
        if expect_success:
            assert task.status == 3, task.error_message
        return task

    return novel, chapter, snapshot, counts, requested, run


@pytest.mark.asyncio
async def test_second_button_extraction_skips_model_and_does_not_add_usage():
    _, _, _, counts, _, run = await extraction_fixture()
    await run()
    before = await ModelUsageRecord.all().count()
    amounts = await ModelUsageRecord.all().values_list('cost', flat=True)
    second = await run()
    assert counts == {'inventory': 1, 'design': 1}
    assert second.response_data['preserved_existing']
    assert len(second.response_data['asset_ids']) == 3
    assert await ModelUsageRecord.all().count() == before
    assert sum(amounts) > 0 and await ModelUsageRecord.all().values_list('cost', flat=True) == amounts


@pytest.mark.asyncio
async def test_missing_prop_reuses_inventory_and_only_completes_the_missing_type():
    novel, _, _, counts, requested, run = await extraction_fixture()
    await run()
    person = await Asset.get(novel=novel, asset_type=1)
    original = person.base_traits
    await Asset.filter(novel=novel, asset_type=3).update(base_traits='')
    await run()
    assert counts == {'inventory': 1, 'design': 2}
    await person.refresh_from_db()
    assert person.base_traits == original
    assert '道具甲' in requested[-1] and ('只返回' in requested[-1] or 'Return only' in requested[-1])
    assert (await Asset.get(novel=novel, asset_type=3)).base_traits
    await run()
    assert counts == {'inventory': 1, 'design': 2}


@pytest.mark.asyncio
async def test_missing_variant_is_repaired_without_regenerating_other_assets():
    from models.asset_variant import AssetVariant
    novel, _, _, counts, _, run = await extraction_fixture(with_variant=True)
    await run()
    await run()
    assert counts == {'inventory': 1, 'design': 1}
    variant = await AssetVariant.get(asset__novel_id=novel.id)
    await AssetVariant.filter(id=variant.id).update(base_traits='')
    await run()
    assert counts == {'inventory': 1, 'design': 2}
    assert (await AssetVariant.get(asset__novel_id=novel.id)).base_traits
    await run()
    assert counts == {'inventory': 1, 'design': 2}


@pytest.mark.asyncio
async def test_deleted_prop_is_not_silently_restored_or_charged_again():
    from datetime import datetime, timezone
    novel, _, _, counts, _, run = await extraction_fixture()
    await run()
    await Asset.filter(novel=novel, asset_type=3).update(deleted_at=datetime.now(timezone.utc))
    from services.creation_agent.skill_execution import SkillExecution
    from models.creation_agent import AgentMessage
    task = await AiTask.filter(task_type=1, status=3).first()
    execution = SkillExecution({**task.request_params, 'task_id': str(task.id)}, await AgentMessage.get(task=task, role='assistant'), AsyncMock())
    with pytest.raises(ValueError, match='恢复'):
        await extraction_reuse.find(execution, task.request_params['chapter_id'])
    assert counts == {'inventory': 1, 'design': 1}
    assert await Asset.filter(novel=novel, asset_type=3).count() == 0


@pytest.mark.asyncio
async def test_cover_only_changes_do_not_invalidate_completed_extraction():
    novel, _, _, counts, _, run = await extraction_fixture()
    await run()
    novel.cover = '/media/new-cover.png'
    await novel.save()
    await run()
    assert counts == {'inventory': 1, 'design': 1}


@pytest.mark.asyncio
async def test_invalid_saved_prompt_is_corrected_once_then_reused():
    novel, _, _, counts, _, run = await extraction_fixture()
    await run()
    await Asset.filter(novel=novel, asset_type=3).update(base_traits='旧的不完整格式')
    await run()
    await run()
    assert counts == {'inventory': 1, 'design': 2}
    assert (await Asset.get(novel=novel, asset_type=3)).base_traits != '旧的不完整格式'


@pytest.mark.asyncio
async def test_variant_repair_preserves_a_concurrent_user_edit():
    from models.asset_variant import AssetVariant
    changed = {}
    async def edit():
        await AssetVariant.filter(id=changed['id']).update(base_traits=changed['prompt'])
    novel, _, snapshot, counts, _, run = await extraction_fixture(with_variant=True, repair_hook=edit)
    await run()
    variant = await AssetVariant.get(asset__novel_id=novel.id)
    changed.update(id=variant.id, prompt=fixed_asset_prompt(snapshot=snapshot) + '\n人工确认的补充要求')
    await AssetVariant.filter(id=variant.id).update(base_traits='')
    failed = await run(expect_success=False)
    assert failed.status == 4 and '人工编辑' in failed.error_message
    await variant.refresh_from_db()
    assert variant.base_traits == changed['prompt']
    assert counts == {'inventory': 1, 'design': 2}


@pytest.mark.asyncio
async def test_legacy_verified_receipts_are_reused_without_a_schema_migration():
    from models.agent_operation import AgentOperation
    _, _, _, counts, _, run = await extraction_fixture()
    first = await run()
    await AgentOperation.filter(task=first, key='extraction:inputs').delete()
    await run()
    assert counts == {'inventory': 1, 'design': 1}


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source', 'project', 'protocol', 'failed', 'missing_persist', 'placeholder'])
async def test_reuse_requires_verified_complete_current_source_and_rules(change):
    from models.agent_operation import AgentOperation
    from models.creation_agent import AgentMessage
    from services.creation_agent.skill_execution import SkillExecution
    novel, chapter, snapshot, _, _, run = await extraction_fixture()
    first = await run()
    if change == 'source':
        chapter.content += '原文有新内容。'
        await chapter.save()
    elif change == 'project':
        novel.custom_style_prompt = '新风格'
        await novel.save()
    elif change == 'protocol':
        snapshot = snapshot.model_copy(update={'revision': 'new-protocol'})
    elif change == 'failed':
        await AiTask.filter(id=first.id).update(status=4)
    elif change == 'missing_persist':
        await AgentOperation.filter(task=first, key='persist:assets').delete()
    else:
        await Asset.filter(novel=novel, asset_type=3).update(metadata={'analysis_source': 'project_analysis'})
    execution = SkillExecution({**first.request_params, 'task_id': str(first.id), 'skill_snapshot': snapshot.model_dump()},
        await AgentMessage.get(task=first, role='assistant'), AsyncMock())
    reusable = await extraction_reuse.find(execution, chapter.id)
    assert reusable is None or not reusable.complete


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['regenerate', 'revise'])
async def test_explicit_regeneration_and_revision_never_skip(mode):
    from models.creation_agent import AgentMessage
    from schemas.creation_plan import CreationPlanStep
    from services.creation_agent.plan_execution import existing_result
    from services.creation_agent.skill_execution import SkillExecution
    _, chapter, _, _, _, run = await extraction_fixture()
    first = await run()
    execution = SkillExecution(first.request_params, await AgentMessage.get(task=first, role='assistant'), AsyncMock())
    step = CreationPlanStep(id='assets', operation='assets', mode=mode, target_id=chapter.id, instructions='显式修改', label='修改')
    assert await existing_result(step, chapter.id, execution) is None


@pytest.mark.asyncio
async def test_existing_roles_alone_are_not_proof_that_all_asset_types_were_extracted():
    from models.creation_agent import AgentMessage
    from services.creation_agent.skill_execution import SkillExecution
    novel, chapter, snapshot, _, _, run = await extraction_fixture()
    await Asset.create(novel=novel, asset_type=1, canonical_name='已有人物', base_traits=fixed_asset_prompt(snapshot=snapshot))
    task = await chapter_controller.extract(chapter.id)
    task.request_params['skill_snapshot'] = snapshot.model_dump()
    from services.creation_agent.production import conversation_for_task
    message = await conversation_for_task(task)
    execution = SkillExecution({**task.request_params, 'task_id': str(task.id)}, message, AsyncMock())
    assert await extraction_reuse.find(execution, chapter.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,completed', [('fill_missing', 10), ('fill_missing', 9), ('revise', 10)])
async def test_book_asset_plan_does_not_reread_completed_chapters(mode, completed):
    from types import SimpleNamespace
    from schemas.creation_plan import CreationBrief, CreativeRequirement, CreationPlanDraft, CreationPlanStep, SourceReading
    from services.creation_agent.plans import CreationPlanner
    from test.test_services.test_creation_plans import plan_fixture
    _, request, chapters, _, source, execution = await plan_fixture()
    message = '补齐全书资产，保留已经完成的结果。' if mode == 'fill_missing' else '重新提取全书资产。'
    request = request.model_copy(update={'write_scope': 'project', 'message': message})
    source.content = message
    await source.save()
    calls = []
    async def find(_, chapter_id):
        return SimpleNamespace(complete=chapter_id in {c.id for c in chapters[:completed]})
    async def generate(skill, facts, output_type, **options):
        calls.append((skill, facts))
        if skill == 'planning_request':
            return CreationBrief(operations=['assets'], asset_mode=mode, write_selection='project',
                project_scope_quote=message, read_chapter_ids=[c.id for c in chapters],
                requirements=[CreativeRequirement(id='assets', instruction=message, source_quote=message, acceptance=message)])
        if skill == 'source_reading':
            return SourceReading(summary='章节事实已核对', candidates=[])
        if skill == 'creation_planning':
            return CreationPlanDraft(summary='补齐资产', steps=[CreationPlanStep(id=f'c{c.id}', operation='assets',
                target_id=c.id, mode=mode, requirement_ids=['assets'], instructions=message, label='资产') for c in chapters])
        raise AssertionError(skill)
    with patch.object(execution, 'generate', side_effect=generate), patch.object(extraction_reuse, 'find', side_effect=find):
        plan = await CreationPlanner(execution, source).prepare(request)
    assert len(plan.steps) == 10
    expected_reads = 10 if mode == 'revise' else 10 - completed
    assert sum(skill == 'source_reading' for skill, _ in calls) == expected_reads
    assert sum(skill == 'creation_planning' for skill, _ in calls) == (0 if expected_reads == 0 else 1)


def test_reuse_plan_prompt_preserves_source_and_mode_contracts():
    from prompts.creation_plan import plan_reference_instructions
    for language in ['zh', 'en']:
        prompt = plan_reference_instructions(language)
        assert 'reused_asset_chapter_ids' in prompt and 'brief.asset_mode' in prompt
        assert 'reference_id' in prompt


def test_misplaced_duplicate_scene_cannot_poison_an_otherwise_complete_candidate():
    from services.extraction.validation import AssetCandidateValidator
    from services.extraction.extractor import AssetExtractionResult, validate_required_design_assets
    snapshot = synthetic_snapshot()
    scope = ((1, '角色甲'), (2, '维修室'), (3, '面板'))
    validator = AssetCandidateValidator(AssetExtractionResult, scope)
    draft = validator.draft_type.model_validate({'persons': [
        {'name': '角色甲', 'base_traits': fixed_asset_prompt(snapshot=snapshot)},
        {'name': '维修室', 'base_traits': fixed_asset_prompt(kind='scene', snapshot=snapshot)}],
        'scenes': [{'name': '维修室', 'base_traits': fixed_asset_prompt(kind='scene', snapshot=snapshot)}],
        'items': [{'name': '面板', 'base_traits': fixed_asset_prompt(kind='item', snapshot=snapshot)}]})
    merged = validator.merge(draft, snapshot, 'zh', '16:9')
    validate_required_design_assets(merged, scope)
    assert not validator.issues and [person.name for person in merged.persons] == ['角色甲']


def test_scope_filter_never_drops_a_required_person_sharing_a_scene_name():
    from services.extraction.validation import AssetCandidateValidator
    from services.extraction.extractor import AssetExtractionResult
    snapshot = synthetic_snapshot()
    validator = AssetCandidateValidator(AssetExtractionResult, ((1, '同名'), (2, '同名')))
    draft = validator.draft_type.model_validate({'persons': [{'name': '同名', 'base_traits': fixed_asset_prompt(snapshot=snapshot)}],
        'scenes': [{'name': '同名', 'base_traits': fixed_asset_prompt(kind='scene', snapshot=snapshot)}], 'items': []})
    merged = validator.merge(draft, snapshot, 'zh', '16:9')
    assert len(merged.persons) == len(merged.scenes) == 1 and not validator.issues
