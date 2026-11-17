"""Retired tasks stop before generation; modern context failures do not write assets."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from models.novel import Novel
from models.chapter import Chapter
from models.asset import Asset
from services.extraction.handler import ExtractionTaskHandler
from services.creation_agent.skill_execution import current_execution


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['assets', 'storyboard', 'screenplay', 'story'])
async def test_retired_text_task_requires_new_submission_without_model_call(kind, monkeypatch):
    from services.chapter_screenplay import ScreenplayHandler
    from services.storyboard.handler import StoryboardTaskHandler
    from services.project_analysis.handler import ProjectAnalysisTaskHandler
    novel = await Novel.create(name='历史任务')
    chapter = await Chapter.create(novel=novel, number=1, name='第一集', content='原文')
    generate = AsyncMock(side_effect=AssertionError('no provider request for retired tasks'))
    monkeypatch.setattr('services.creation_agent.strict_text.generate', generate)
    handlers = {'assets': ExtractionTaskHandler(), 'storyboard': StoryboardTaskHandler(),
                'screenplay': ScreenplayHandler(), 'story': ProjectAnalysisTaskHandler()}
    with pytest.raises(ValueError, match='旧版文本任务已停用'):
        await handlers[kind].execute({'novel_id': novel.id, 'chapter_id': chapter.id})
    generate.assert_not_awaited()
    from services.creation_agent.production_resume import supports_production_resume
    assert not supports_production_resume(SimpleNamespace(task_type={'assets': 1, 'storyboard': 3, 'story': 5, 'screenplay': 10}[kind],
        request_params={'workflow_version': 'agent-skills-v1'}))
    assert not await Asset.filter(novel=novel).exists()


@pytest.mark.asyncio
async def test_context_failure_stops_generation_and_persistence():
    loader = SimpleNamespace(load=AsyncMock(side_effect=ValueError('章节不属于当前项目')))
    writer = SimpleNamespace(save_result=AsyncMock())
    execution = SimpleNamespace(generate_strict=AsyncMock())
    token = current_execution.set(execution)
    try:
        with pytest.raises(ValueError, match='章节不属于当前项目'):
            await ExtractionTaskHandler(context_loader=loader, upsert_service=writer).execute(
                {'novel_id': 1, 'chapter_id': 2, 'output_contract': {'name': 'assets'}})
    finally:
        current_execution.reset(token)
    execution.generate_strict.assert_not_awaited()
    writer.save_result.assert_not_awaited()
