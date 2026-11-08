"""Story character references must never become usable visual assets."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from services.project_analysis.handler import BookAnalysis, KeyCharacter, ProjectAnalysisTaskHandler
from test.test_services.test_project_analysis_handler import FakeLlmClient


@pytest.mark.asyncio
async def test_analysis_keeps_character_references_without_creating_or_changing_assets(monkeypatch):
    novel = await Novel.create(name='人物参考', content='第一章\n林舟走回故乡。')
    await Chapter.create(novel=novel, number=1, name='归来', content='林舟走回故乡。')
    await AiModelConfig.create(task_type=5, name='analysis', model='test', base_url='https://example.invalid', api_key='test', is_active=True)
    existing = await Asset.create(novel=novel, asset_type=1, canonical_name='林舟',
        aliases=['已确认别名'], description='已确认的人物', base_traits='已确认完整设计',
        source_chapters=[1], main_image='/media/keep.png', metadata={'voice_reference_id': 73})
    before = await Asset.filter(id=existing.id).values()
    analysis = BookAnalysis(book_types=['归乡'], story_outline='林舟回到故乡。', key_characters=[
        KeyCharacter(name='林舟', role='主角', aliases=['新分析别名'], description='归乡的青年', base_traits='分析概述', chapter_numbers=[1]),
        KeyCharacter(name='师父', role='配角', description='过去的导师', base_traits='不应成为资产', chapter_numbers=[1]),
    ])
    monkeypatch.setattr('services.project_analysis.handler.AsyncOpenAI', lambda **_: FakeLlmClient(analysis))
    for _ in range(2):
        result = await ProjectAnalysisTaskHandler().execute({'novel_id': novel.id, 'include_cover': False})
        assert result['analysis_completed'] is True
        assert [item['name'] for item in result['key_characters']] == ['林舟', '师父']
    assert await Asset.filter(novel=novel).count() == 1
    assert await Asset.filter(id=existing.id).values() == before
    await novel.refresh_from_db()
    assert novel.story_outline == analysis.story_outline


@pytest.mark.asyncio
async def test_analysis_character_becomes_an_asset_only_after_explicit_extraction(monkeypatch):
    from services.extraction.extractor import AssetExtractionResult, Person
    from services.extraction.persistence import AssetUpsertService
    novel = await Novel.create(name='先参考后提取', content='第一章\n林舟来了。')
    await Chapter.create(novel=novel, number=1, name='开始', content='林舟来了。')
    await AiModelConfig.create(task_type=5, name='analysis', model='test', base_url='https://example.invalid', api_key='test', is_active=True)
    analysis = BookAnalysis(book_types=[], story_outline='林舟来了。', key_characters=[
        KeyCharacter(name='林舟', role='主角', description='少年', base_traits='概述', chapter_numbers=[1])])
    monkeypatch.setattr('services.project_analysis.handler.AsyncOpenAI', lambda **_: FakeLlmClient(analysis))
    await ProjectAnalysisTaskHandler().execute({'novel_id': novel.id, 'include_cover': False})
    assert not await Asset.filter(novel=novel).exists()
    await AssetUpsertService().save_result(novel_id=novel.id, chapter_number=1,
        result=AssetExtractionResult(persons=[Person(name='林舟', description='少年', base_traits='正式提取的完整设计')], scenes=[], items=[]))
    asset = await Asset.get(novel=novel)
    assert asset.base_traits == '正式提取的完整设计'
    assert (asset.metadata or {}).get('analysis_source') != 'project_analysis'


def test_analysis_schema_requests_story_references_without_visual_design():
    schema = KeyCharacter.model_json_schema()
    assert 'base_traits' not in schema['properties']
    assert KeyCharacter(name='林舟', role='主角', description='归来的青年').base_traits == ''
    # Previously saved analysis results remain readable.
    assert KeyCharacter(name='林舟', role='主角', description='青年', base_traits='旧概述').base_traits == '旧概述'


def test_analysis_prompt_keeps_reference_only_rule_in_both_languages():
    from prompts.project_analysis import render_analysis_messages
    for language in ('zh', 'en'):
        prompt = render_analysis_messages(name='故事', chapter_count=1, material='原文', prompt_language=language)[0]['content']
        assert f'language={language}' in prompt
        assert '关键人物只作为故事参考' in prompt
        assert '不生成外观设计、生图提示词或资产占位' in prompt


@pytest.mark.asyncio
async def test_legacy_analysis_placeholder_cannot_submit_paid_image_generation(monkeypatch):
    from controllers.asset import asset_controller
    novel = await Novel.create(name='旧占位保护')
    asset = await Asset.create(novel=novel, asset_type=1, canonical_name='旧分析人物', base_traits='分析的简略概述',
        metadata={'analysis_source': 'project_analysis'})
    choose_model = AsyncMock()
    submit = AsyncMock()
    monkeypatch.setattr('controllers.asset.ai_model_config_controller.get_active', choose_model)
    monkeypatch.setattr('controllers.asset.ai_task_executor.submit', submit)
    with pytest.raises(HTTPException) as error:
        await asset_controller.reference(asset.id)
    assert error.value.status_code == 409
    assert '资产提取' in str(error.value.detail)
    choose_model.assert_not_awaited()
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_analysis_persists_story_references_without_creating_assets(monkeypatch):
    from controllers.novel import novel_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.skill_execution import SkillExecution
    from test.test_services.test_skill_workflow import enabled_project
    novel, _, _ = await enabled_project()
    novel.content = '第一章\n林舟回到了故乡。'
    await novel.save()

    async def generate(self, skill, facts, output_type, **kwargs):
        assert skill == 'story' and output_type is BookAnalysis
        return BookAnalysis(book_types=['归乡'], story_outline='少年重返故乡。', key_characters=[
            KeyCharacter(name='林舟', role='主角', description='重返故乡的少年', chapter_numbers=[1])])

    monkeypatch.setattr(SkillExecution, 'generate', generate)
    task = await novel_controller.analyze(novel.id, include_cover=False)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert task.response_data['analysis_completed'] is True
    assert task.response_data['key_characters'][0]['name'] == '林舟'
    assert not await Asset.filter(novel=novel).exists()
