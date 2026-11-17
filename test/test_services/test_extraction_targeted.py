"""Asset plan scopes remain enforced independently of the generation transport."""
from unittest.mock import AsyncMock, patch
import pytest
from schemas.creation_plan import CreativeRequirement, CreationPlanStep


def test_legacy_plans_default_to_complete_chapter_scope():
    from schemas.creation_plan import CreationBrief, CreationPlanStep
    assert CreationBrief.model_validate({}).asset_scope == 'chapter'
    step = CreationPlanStep.model_validate({'id': 'old', 'operation': 'assets', 'target_id': 1,
        'instructions': '整章提取', 'label': '资产'})
    assert step.asset_scope == 'chapter'


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
