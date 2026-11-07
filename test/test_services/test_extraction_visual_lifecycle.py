import json

import pytest

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.novel import Novel
from services.extraction.context import ExtractionContextLoader
from services.extraction.extractor import AssetExtractionResult, Person, Scene, Item
from services.extraction.messages import ExtractionMessageBuilder
from services.extraction.persistence import AssetUpsertService


def result(model, key, **values):
    return AssetExtractionResult(persons=[], scenes=[], items=[]).model_copy(
        update={key: [model(name='主资产', base_traits='完整的正式形象', **values)]})


@pytest.mark.asyncio
@pytest.mark.parametrize('model,key,kind', [(Person, 'persons', 1), (Scene, 'scenes', 2), (Item, 'items', 3)])
async def test_fill_missing_promotes_analysis_placeholder_then_preserves_confirmed_design(model, key, kind):
    novel = await Novel.create(name='占位到正式设计')
    asset = await Asset.create(novel=novel, asset_type=kind, canonical_name='主资产',
        base_traits='分析占位', source_chapters=[1, 8], last_updated_chapter=8,
        metadata={'analysis_source': 'project_analysis', 'voice_reference_id': 73},
        main_image='/media/keep.png')
    service = AssetUpsertService()
    await service.save_result(novel_id=novel.id, chapter_number=1,
        result=result(model, key), preserve_existing=True)
    await asset.refresh_from_db()
    assert asset.base_traits == '完整的正式形象'
    assert 'analysis_source' not in asset.metadata
    assert asset.metadata['voice_reference_id'] == 73
    assert asset.main_image == '/media/keep.png'
    await service.save_result(novel_id=novel.id, chapter_number=2,
        result=AssetExtractionResult(persons=[], scenes=[], items=[]).model_copy(update={key: [
            model(name='主资产', aliases=['别名'], base_traits='模型措辞变了，没有外形变化')]}),
        preserve_existing=True)
    await asset.refresh_from_db()
    assert asset.base_traits == '完整的正式形象'
    assert asset.source_chapters == [1, 2, 8]
    assert asset.aliases == ['别名']
    assert await AssetVariant.filter(asset=asset).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('model,key,kind', [(Person, 'persons', 1), (Scene, 'scenes', 2), (Item, 'items', 3)])
async def test_visual_change_creates_variant_and_reuses_it_across_chapters(model, key, kind):
    novel = await Novel.create(name='跨章衍生')
    service = AssetUpsertService()
    await service.save_result(novel_id=novel.id, chapter_number=1, result=result(model, key))
    changed = result(model, key, variant={
        'name': '新外形', 'description': '第二阶段', 'base_traits': '新外形完整提示词',
        'change_reason': '本章明确发生成长、换装、建筑重建或道具重铸，改变稳定外形',
    })
    for chapter in (2, 2, 3):
        await service.save_result(novel_id=novel.id, chapter_number=chapter,
            result=changed, preserve_existing=True)
    asset = await Asset.get(novel=novel)
    variant = await AssetVariant.get(asset=asset)
    assert asset.base_traits == '完整的正式形象'
    assert variant.base_traits == '新外形完整提示词'
    assert variant.chapter_numbers == [2, 3]
    assert asset.source_chapters == [1, 2, 3]
    assert await AssetVariant.filter(asset=asset).count() == 1


@pytest.mark.asyncio
async def test_extraction_context_exposes_placeholder_status_and_existing_variants():
    novel = await Novel.create(name='形态上下文')
    chapter = await Chapter.create(novel=novel, number=3, name='第三章', content='正文')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主资产',
        metadata={'analysis_source': 'project_analysis', 'internal_note': 'private'})
    await AssetVariant.create(asset=asset, name='成年', base_traits='成年形象',
        description='长大之后', chapter_numbers=[2], metadata={'internal_note': 'private'})
    context = await ExtractionContextLoader().load(novel_id=novel.id, chapter_id=chapter.id)
    messages = ExtractionMessageBuilder().build(context, 'zh')
    known = json.loads(messages[2]['content'])[0]
    assert known['metadata']['analysis_source'] == 'project_analysis'
    assert known['variants'][0]['name'] == '成年'
    assert known['variants'][0]['base_traits'] == '成年形象'
    assert 'private' not in messages[2]['content']


@pytest.mark.asyncio
async def test_reanalysis_never_demotes_formal_design_or_erases_media_bindings():
    from services.project_analysis.handler import _sync_character_assets, KeyCharacter

    novel = await Novel.create(name='重新分析保留正式设计')
    formal = await Asset.create(novel=novel, asset_type=1, canonical_name='正式人物',
        base_traits='已确认形象', description='已确认描述', aliases=['老别名'],
        source_chapters=[1], last_updated_chapter=1,
        main_image='/media/formal.png', metadata={'voice_reference_id': 73})
    placeholder = await Asset.create(novel=novel, asset_type=1, canonical_name='占位人物',
        base_traits='旧占位', metadata={'analysis_source': 'project_analysis', 'voice_reference_id': 74})
    for _ in range(2):
        await _sync_character_assets(novel, [KeyCharacter(name=name, aliases=['新别名'], role='配角',
            description='新的分析概述', base_traits='新的占位', chapter_numbers=[2])
            for name in ('正式人物', '占位人物')], 2, 'zh')
    await formal.refresh_from_db()
    await placeholder.refresh_from_db()
    assert formal.base_traits == '已确认形象'
    assert formal.description == '已确认描述'
    assert formal.source_chapters == [1, 2]
    assert formal.aliases == ['老别名', '新别名']
    assert formal.last_updated_chapter == 1
    assert formal.main_image == '/media/formal.png'
    assert formal.metadata == {'voice_reference_id': 73, 'role': '配角'}
    assert placeholder.base_traits == '新的占位'
    assert placeholder.metadata['analysis_source'] == 'project_analysis'
    assert placeholder.metadata['voice_reference_id'] == 74


@pytest.mark.asyncio
async def test_existing_variant_design_and_images_are_not_overwritten_by_reextraction():
    novel = await Novel.create(name='沿用衍生')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主资产', base_traits='少年')
    variant = await AssetVariant.create(asset=asset, name='成年', base_traits='成年原貌',
        chapter_numbers=[2], images=['/media/adult.png'], metadata={'voice_reference_id': 73})
    await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=3,
        result=result(Person, 'persons', variant={'name': '成年', 'base_traits': '模型改写',
            'change_reason': '本章沿用成年外形'}))
    await variant.refresh_from_db()
    assert variant.base_traits == '成年原貌'
    assert variant.images == ['/media/adult.png']
    assert variant.metadata == {'voice_reference_id': 73}
    assert variant.chapter_numbers == [2, 3]


@pytest.mark.asyncio
async def test_variant_failure_rolls_back_placeholder_promotion_and_other_asset_changes():
    novel = await Novel.create(name='形态事务')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主资产',
        base_traits='占位', metadata={'analysis_source': 'project_analysis'})
    await AssetVariant.create(asset=asset, name='已分配形态', chapter_numbers=[2])
    with pytest.raises(ValueError, match='已有形态'):
        await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=2,
            result=result(Person, 'persons', variant={'name': '冲突形态', 'base_traits': '完整形象',
                'change_reason': '本章外形变化'}), preserve_existing=True)
    await asset.refresh_from_db()
    assert asset.base_traits == '占位'
    assert asset.metadata['analysis_source'] == 'project_analysis'
    assert await AssetVariant.filter(asset=asset).count() == 1


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('kind,model,key', [('person', Person, 'persons'), ('scene', Scene, 'scenes'), ('item', Item, 'items')])
def test_variant_prompts_follow_same_language_and_mandatory_output_contract(language, kind, model, key):
    from prompts.skill_pack import SkillSnapshot, snapshot_skills, instructions
    from services.extraction.extractor import validate_asset_prompt_contract
    from test.test_services.test_asset_design_instructions import fixed_asset_prompt

    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    prompt = fixed_asset_prompt(language, kind, snapshot=snapshot)
    candidate = AssetExtractionResult(persons=[], scenes=[], items=[]).model_copy(update={key: [
        model(name='主体', base_traits=prompt, variant={'name': '变化形态', 'base_traits': prompt,
            'change_reason': '章节明确外观变化'})]})
    validate_asset_prompt_contract(candidate, snapshot, language, '16:9')
    rendered = instructions(snapshot, language, 'assets')
    assert f'language={language}' in rendered
    assert snapshot.read('asset_lifecycle') in rendered
    assert snapshot.read('asset_lifecycle') in instructions(snapshot, language, 'storyboard')
    getattr(candidate, key)[0].variant.base_traits = '简略的占位概述'
    with pytest.raises(ValueError):
        validate_asset_prompt_contract(candidate, snapshot, language, '16:9')


@pytest.mark.parametrize('field', ['name', 'base_traits', 'change_reason'])
def test_variant_requires_concrete_name_design_and_change_evidence(field):
    from services.extraction.extractor import ExtractedVariant
    values = {'name': '成年', 'base_traits': '完整形象', 'change_reason': '十年后长大'}
    values[field] = '  '
    with pytest.raises(ValueError):
        ExtractedVariant(**values)


@pytest.mark.asyncio
async def test_planned_extraction_records_base_promotion_and_variant_for_replay_and_undo(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from models.agent_operation import AgentOperation
    from models.ai_task import AiTask
    from models.creation_agent import PromptChange
    from services.creation_agent.changes import CreationChanges
    from services.creation_agent.skill_execution import current_execution
    from services.extraction.handler import ExtractionTaskHandler
    from test.test_services.test_creation_plans import confirmed_fixture

    _, request, plan, task, execution = await confirmed_fixture()
    step = plan.steps[0]
    step.operation, step.mode = 'assets', 'fill_missing'
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(
        result=plan.model_dump(mode='json'))
    execution.params.update(creation_step_id=step.id, chapter_id=step.target_id)
    asset = await Asset.create(novel_id=plan.novel_id, asset_type=1, canonical_name='主资产',
        base_traits='分析占位', metadata={'analysis_source': 'project_analysis', 'voice_reference_id': 73})
    response = result(Person, 'persons', variant={'name': '成年', 'base_traits': '成年形象',
        'change_reason': '本章从童年回忆转入成年'})
    extractor = SimpleNamespace(extract=AsyncMock(return_value=response), last_usage={})
    handler = ExtractionTaskHandler(extractor_factory=lambda *args, **kwargs: extractor)
    monkeypatch.setattr('services.extraction.handler.AsyncOpenAI', lambda **kwargs: None)
    params = {**execution.params, 'base_url': 'https://example.invalid', 'api_key': 'test', 'model': 'test'}
    token = current_execution.set(execution)
    try:
        saved = await handler.execute(params)
        replay = await handler.execute(params)
    finally:
        current_execution.reset(token)
    assert saved == replay
    change = await PromptChange.get(task=task)
    assert [item['kind'] for item in change.changes] == ['asset', 'variant']
    variant = await AssetVariant.get(asset=asset)
    assert saved['variant_ids'] == [variant.id]
    assert saved['asset_ids'] == [asset.id]
    assert await AssetVariant.filter(asset=asset).count() == 1
    assert change.changes[0]['before']['metadata']['analysis_source'] == 'project_analysis'
    assert 'analysis_source' not in change.changes[0]['after']['metadata']
    await AiTask.filter(id=task.id).update(status=3)
    await CreationChanges(novel_id=plan.novel_id, task_id=task.id,
        request=request, max_batch_size=10).undo(change.id)
    await asset.refresh_from_db()
    assert asset.base_traits == '分析占位'
    assert asset.metadata == {'analysis_source': 'project_analysis', 'voice_reference_id': 73}
    assert await AssetVariant.filter(asset=asset).count() == 0
