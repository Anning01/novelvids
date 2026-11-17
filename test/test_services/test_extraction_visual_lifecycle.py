from test.text_task_fixtures import analysis_execution, execute_analysis
from test.agent_stream_fixtures import streaming_model
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
    facts = ExtractionMessageBuilder().build(context)
    known = facts['known_assets'][0]
    assert known['metadata']['analysis_source'] == 'project_analysis'
    assert known['variants'][0]['name'] == '成年'
    assert known['variants'][0]['base_traits'] == '成年形象'
    assert 'private' not in str(facts['known_assets'])


@pytest.mark.asyncio
async def test_reanalysis_never_demotes_formal_design_or_erases_media_bindings():
    from unittest.mock import patch
    from models.config import AiModelConfig
    from services.project_analysis.handler import BookAnalysis, ProjectAnalysisTaskHandler, KeyCharacter

    novel = await Novel.create(name='重新分析保留正式设计', content='第一章\n人物归来。第二章\n人物离开。')
    for number in (1, 2):
        await Chapter.create(novel=novel, number=number, name=f'章节{number}', content='人物在场。')
    await AiModelConfig.create(task_type=5, name='analysis', model='test', base_url='https://example.invalid', api_key='test', is_active=True)
    formal = await Asset.create(novel=novel, asset_type=1, canonical_name='正式人物',
        base_traits='已确认形象', description='已确认描述', aliases=['老别名'],
        source_chapters=[1], last_updated_chapter=1,
        main_image='/media/formal.png', metadata={'voice_reference_id': 73})
    placeholder = await Asset.create(novel=novel, asset_type=1, canonical_name='占位人物',
        base_traits='旧占位', metadata={'analysis_source': 'project_analysis', 'voice_reference_id': 74})
    analysis = BookAnalysis(book_types=[], story_outline='人物归来后离开。', key_characters=[KeyCharacter(name=name, aliases=['新别名'], role='配角',
            description='新的分析概述', base_traits='新的占位', chapter_numbers=[2])
            for name in ('正式人物', '占位人物')])
    with analysis_execution(analysis):
        for _ in range(2):
            await execute_analysis({'novel_id': novel.id, 'include_cover': False})
    await formal.refresh_from_db()
    await placeholder.refresh_from_db()
    assert formal.base_traits == '已确认形象'
    assert formal.description == '已确认描述'
    assert formal.source_chapters == [1]
    assert formal.aliases == ['老别名']
    assert formal.last_updated_chapter == 1
    assert formal.main_image == '/media/formal.png'
    assert formal.metadata == {'voice_reference_id': 73}
    assert placeholder.base_traits == '旧占位'
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
    with pytest.raises(ValueError, match='绑定形态不存在'):
        await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=2,
            result=result(Person, 'persons', variant={'name': '冲突形态', 'existing_variant_id': 999999, 'base_traits': '完整形象',
                'change_reason': '本章外形变化'}), preserve_existing=True)
    await asset.refresh_from_db()
    assert asset.base_traits == '占位'
    assert asset.metadata['analysis_source'] == 'project_analysis'
    assert await AssetVariant.filter(asset=asset).count() == 1




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
    from test.test_services.test_strict_production import asset_payload
    from schemas.text_task_contracts import output_contract
    from prompts.skill_pack import read_skill
    import json
    specs = json.loads(read_skill('asset_contract'))['zh']
    contract = output_contract('assets', asset_specifications=specs)
    contract['rendering'] = {'asset_specifications': specs, 'aspect_ratio': '16:9'}
    payload = asset_payload()
    payload['persons'][0]['name'] = '主资产'
    payload['persons'][0]['variant'] = {'existing_variant_id': None, 'name': '成年', 'description': '',
        'change_reason': '本章从童年回忆转入成年', 'design': '成年形象', 'visual_fields': payload['persons'][0]['visual_fields']}
    execution.params['output_contract'] = contract
    execution.generate_strict = AsyncMock(return_value=payload)
    handler = ExtractionTaskHandler()
    params = execution.params
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


@pytest.mark.asyncio
async def test_chapter_linked_placeholders_require_design_even_when_only_mentioned():
    novel = await Novel.create(name='本章关联占位补全')
    chapter = await Chapter.create(novel=novel, number=1, name='第一章', content='主角提到峰主的威胁。')
    placeholder = await Asset.create(novel=novel, asset_type=1, canonical_name='峰主',
        source_chapters=[1, 60], base_traits='分析占位', metadata={'analysis_source': 'project_analysis'})
    await Asset.create(novel=novel, asset_type=1, canonical_name='后续人物',
        source_chapters=[60], base_traits='后续占位', metadata={'analysis_source': 'project_analysis'})
    await Asset.create(novel=novel, asset_type=1, canonical_name='已有正式人物',
        source_chapters=[1], base_traits='正式设计')
    context = await ExtractionContextLoader().load(novel_id=novel.id, chapter_id=chapter.id)
    assert [asset.id for asset in context.required_design_assets] == [placeholder.id]
    registry = ExtractionMessageBuilder().build(context)['known_assets']
    assert [asset['id'] for asset in registry if asset.get('requires_design_completion')] == [placeholder.id]






@pytest.mark.asyncio
async def test_return_to_registered_identity_uses_the_same_variant_across_chapters():
    novel = await Novel.create(name='三种身份')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主资产', base_traits='基础设计')
    forms = [await AssetVariant.create(asset=asset, name=name, base_traits=name,
        images=[name + '.png'], chapter_numbers=[number])
        for number, name in enumerate(('行脚医装', '官服', '夜行装'), 1)]
    service = AssetUpsertService()
    for chapter, index, label in [(4, 2, '夜行装'), (9, 1, '巡官'), (10, 0, '郎中装'), (10, 0, '郎中装')]:
        form = forms[index]
        saved = await service.save_result(novel_id=novel.id, chapter_number=chapter, include_ids=True,
            result=result(Person, 'persons', variant={'name': label, 'existing_variant_id': form.id,
                'base_traits': '换一种说法', 'change_reason': '剧本沿用这一身份的旧装'}))
        assert saved['persons'][0]['variant_id'] == form.id
    await forms[0].refresh_from_db()
    assert forms[0].chapter_numbers == [1, 10]
    assert forms[0].base_traits == '行脚医装' and forms[0].images == ['行脚医装.png']
    assert await AssetVariant.filter(asset=asset).count() == 3


@pytest.mark.asyncio
async def test_invalid_reuse_reference_cannot_fall_back_to_creating_or_binding_a_namesake():
    novel = await Novel.create(name='核对形态归属')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='主资产', base_traits='基础设计')
    mine = await AssetVariant.create(asset=asset, name='医装', chapter_numbers=[1])
    other = await Asset.create(novel=novel, asset_type=1, canonical_name='另一人')
    foreign = await AssetVariant.create(asset=other, name='医装')
    other_form = await AssetVariant.create(asset=asset, name='捕房官服', chapter_numbers=[9])
    for variant_id in (foreign.id, foreign.id + 1000, other_form.id):
        with pytest.raises(ValueError):
            await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=10,
                result=result(Person, 'persons', variant={'name':'医装', 'existing_variant_id':variant_id,
                    'base_traits':'候选', 'change_reason':'沿用'}))
    await mine.refresh_from_db()
    assert mine.chapter_numbers == [1]
    assert await AssetVariant.filter(asset=asset).count() == 2
