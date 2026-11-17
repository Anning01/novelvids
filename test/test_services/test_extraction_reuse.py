"""Read-only reuse of completed historical receipts; no legacy model execution."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from services.extraction.reuse import extraction_reuse
from test.test_services.test_asset_design_instructions import synthetic_snapshot, fixed_asset_prompt


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







async def historical_receipt():
    from models.novel import Novel
    from models.chapter import Chapter
    from models.ai_task import AiTask
    from models.agent_operation import AgentOperation
    from services.extraction.context import ExtractionContextLoader
    from services.extraction.extractor import AssetExtractionResult, Person
    from services.extraction.persistence import AssetUpsertService
    novel = await Novel.create(name='已完成的旧任务')
    chapter = await Chapter.create(novel=novel, number=1, name='第一章', content='人物甲回家。')
    snapshot = synthetic_snapshot()
    task = await AiTask.create(task_type=1, status=3, request_params={'novel_id': novel.id, 'chapter_id': chapter.id})
    execution = SimpleNamespace(params={**task.request_params, 'task_id': str(task.id)}, snapshot=snapshot, language='zh')
    accepted = AssetExtractionResult(persons=[Person(name='人物甲', base_traits=fixed_asset_prompt(snapshot=snapshot))], scenes=[], items=[])
    summary = await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=1, result=accepted, include_ids=True)
    context = await ExtractionContextLoader().load(novel_id=novel.id, chapter_id=chapter.id)
    revision = await extraction_reuse.input_revision(execution, context, novel)
    await AgentOperation.create(task=task, key=f'extraction:inputs:{chapter.id}:{snapshot.revision}', state='completed', result={'revision': revision})
    await AgentOperation.create(task=task, key='persist:assets', state='completed', result=summary)
    await AgentOperation.create(task=task, key='candidate:assets:', state='completed', result={'accepted': accepted.model_dump(), 'issues': []})
    return novel, chapter, task, execution


@pytest.mark.asyncio
async def test_completed_historical_assets_remain_readable_without_generation():
    _, chapter, _, execution = await historical_receipt()
    result = await extraction_reuse.find(execution, chapter.id)
    assert result and result.complete and result.summary['asset_ids']


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source', 'project', 'protocol', 'failed', 'missing_persist'])
async def test_stale_historical_receipt_cannot_be_reused(change):
    from models.agent_operation import AgentOperation
    novel, chapter, task, execution = await historical_receipt()
    if change == 'source':
        chapter.content += '原文修改'
        await chapter.save()
    elif change == 'project':
        novel.custom_style_prompt = '新风格'
        await novel.save()
    elif change == 'protocol':
        execution.snapshot = execution.snapshot.model_copy(update={'revision': 'changed'})
    elif change == 'failed':
        task.status = 4
        await task.save()
    else:
        await AgentOperation.filter(task=task, key='persist:assets').delete()
    assert await extraction_reuse.find(execution, chapter.id) is None
