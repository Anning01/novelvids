"""Reading selects stable source paragraphs; copied prose is never authoritative."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart, RetryPromptPart
from pydantic_ai.models.function import FunctionModel

from schemas.creation_plan import SourceReading, SourceSelection, ChapterEvidence
from services.creation_agent.source_references import source_paragraphs, resolve_reading, resolve_plan_references
from test.test_services.test_creation_plans import plan_fixture


def facts(text, offset=0):
    return {'chapter_id': 7, 'start': offset, 'end': offset + len(text), 'content': text,
            'paragraphs': source_paragraphs(text, offset), 'reference_protocol': 2}


def reading(**selection):
    return SourceReading(summary='真实剧情摘要', candidates=[SourceSelection(chapter_id=7, **selection)])


def test_paragraph_selection_handles_duplicate_sentences_and_preserves_whitespace():
    text = '门开了。\r\n\r\n门开了。\n他终于走出房间。\n'
    value = facts(text, 4000)
    resolved = resolve_reading(reading(first_paragraph=2, last_paragraph=3), value, require_paragraphs=True)
    candidate = resolved.candidates[0]
    assert candidate.start == 4000 + text.index('门开了。', 1)
    assert candidate.quote == '门开了。\n他终于走出房间。\n'
    assert candidate.reference_id == f'7:{candidate.start}:{candidate.end}'


def test_legacy_quote_with_one_inserted_character_recovers_only_original_text():
    original = '这是用于精确定位开始边界的一段足够长的测试原文。' + '主角收到求救信，决定离开。' + '这是用于精确定位结束边界的一段足够长的测试原文。'
    copied = original.replace('收到求救信', '收到求求救信')
    result = resolve_reading(reading(start=3, end=9, quote=copied), facts(original))
    assert result.candidates[0].quote == original
    assert '求求救' not in result.candidates[0].quote
    assert result.candidates[0].start == 0 and result.candidates[0].end == len(original)


def test_legacy_whitespace_changes_are_restored_from_original_positions():
    original = '城门崩塌。\n\n 主角救出同伴。'
    result = resolve_reading(reading(quote='城门崩塌。主角救出同伴。'), facts(original))
    assert result.candidates[0].quote == original


def test_ambiguous_or_invented_legacy_quote_is_never_guessed():
    for text, quote in [('门开了。门开了。', '门开了。'), ('真实原文', '模型编造的事件')]:
        with pytest.raises(ValueError, match='唯一定位'):
            resolve_reading(reading(quote=quote), facts(text))


@pytest.mark.parametrize('start,end', [(9, 9), (2, 1)])
def test_invalid_paragraph_ids_require_model_correction(start, end):
    with pytest.raises(ValueError, match='段落编号'):
        resolve_reading(reading(first_paragraph=start, last_paragraph=end), facts('第一段\n第二段'), require_paragraphs=True)


def test_plan_uses_reference_id_without_retyping_a_long_quote():
    source = resolve_reading(reading(first_paragraph=2), facts('开头\n关键转折\n结尾')).candidates[0]
    chapter = ChapterEvidence(chapter_id=7, number=1, name='测试', version='v1', characters=10,
        pages=[SourceReading(summary='摘要', candidates=[source])])
    selection = SourceSelection(chapter_id=7, reference_id=source.reference_id)
    resolve_plan_references([selection], [chapter])
    assert selection.start == source.start and selection.end == source.end
    assert selection.quote == '关键转折\n'
    with pytest.raises(ValueError, match='引用编号'):
        resolve_plan_references([SourceSelection(chapter_id=7, reference_id='invented')], [chapter])
    with pytest.raises(ValueError, match='reference_id'):
        resolve_plan_references([SourceSelection(chapter_id=7, start=0, end=1)], [chapter], strict=True)


@pytest.mark.asyncio
async def test_real_model_boundary_repairs_bad_reference_inside_same_call():
    import json
    _, _, _, _, _, execution = await plan_fixture()
    text = '相同的话。\n相同的话。\n最后的冲突。'
    value = facts(text)
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        assert not info.function_tools
        content = next(part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart))
        payload = json.loads(content)['untrusted_task_facts']['input']
        assert 'content' not in payload  # Avoid sending every paragraph twice.
        assert ''.join(p['text'] for p in payload['paragraphs']) == text
        if calls == 2:
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            'summary': '阅读完成', 'candidates': [{'chapter_id': 7, 'first_paragraph': 99 if calls == 1 else 3}]} )])
    model = FunctionModel(respond); model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await execution.generate('source_reading', value, SourceReading)
    assert calls == 2
    assert result.candidates[0].quote == '最后的冲突。'
    assert result.candidates[0].reference_id


@pytest.mark.asyncio
async def test_cached_page_is_resolved_without_another_model_request():
    from models.agent_operation import AgentOperation
    from services.creation_agent.plan_sources import chapter_version, CreationSourceLoader
    _, _, chapters, task, _, execution = await plan_fixture()
    chapter = chapters[0]
    chapter.content = '这是足够长且唯一的起始定位文本，保证不需要模糊匹配。中间内容。这是足够长且唯一的结束定位文本，保证取回真实原文。'
    await chapter.save(update_fields=['content'])
    key = f'model:source_reading:SourceReading:{chapter.id}:{chapter_version(chapter)}:0'
    cached = SourceReading(summary='已完成的摘要', candidates=[SourceSelection(chapter_id=chapter.id,
        quote=chapter.content.replace('中间内容', '中间间内容'))])
    await AgentOperation.create(task=task, key=key, state='completed', external=True, result=cached.model_dump(mode='json'))
    model = FunctionModel(lambda *_: (_ for _ in ()).throw(AssertionError('Must replay saved response')))
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await CreationSourceLoader(execution).read([chapter.id], [])
    assert result[0].pages[0].candidates[0].quote == chapter.content
    assert (await AgentOperation.get(task=task, key=key)).result == cached.model_dump(mode='json')


@pytest.mark.asyncio
async def test_exhausted_reference_validation_is_not_an_uncertain_external_submission():
    from models.agent_operation import AgentOperation
    from pydantic_ai.exceptions import UnexpectedModelBehavior
    _, _, _, task, _, execution = await plan_fixture()
    def respond(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
            'summary': '摘要', 'candidates': [{'chapter_id': 7, 'first_paragraph': 999}]} )])
    model = FunctionModel(respond); model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model), pytest.raises(UnexpectedModelBehavior):
        await execution.generate('source_reading', facts('只有一个段落'), SourceReading)
    receipt = await AgentOperation.get(task=task, key='model:source_reading:SourceReading:')
    assert receipt.state == 'failed'


@pytest.mark.asyncio
async def test_complete_planner_repairs_an_invalid_evidence_id_before_saving():
    import json
    from services.creation_agent.plans import CreationPlanner
    from test.test_services.test_creation_plans import plan_model
    _, request, chapters, task, source, execution = await plan_fixture()
    base = plan_model(request, chapters)
    plan_attempts = 0
    reads = 0
    async def respond(messages, info):
        nonlocal plan_attempts, reads
        content = next(part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart))
        payload = json.loads(content)['untrusted_task_facts']['input']
        if 'paragraphs' in payload:
            reads += 1
            value = {'summary': '本章事件', 'candidates': [{'chapter_id': payload['chapter_id'], 'first_paragraph': 1,
                'last_paragraph': payload['paragraphs'][-1]['id']}]}
        elif 'brief' in payload:
            plan_attempts += 1
            draft = await base('creation_planning', payload, None)
            ref = payload['chapters'][7]['pages'][0]['candidates'][0]['reference_id']
            draft.steps[0].sources = [SourceSelection(chapter_id=chapters[7].id,
                reference_id='unknown' if plan_attempts == 1 else ref)]
            value = draft.model_dump()
        else:
            value = (await base('planning_request', payload, None)).model_dump()
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, value)])
    model = FunctionModel(respond); model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await CreationPlanner(execution, source).prepare(request)
    assert reads == 10 and plan_attempts == 2
    assert result.excerpts[0].text == chapters[7].content
    assert result.steps[0].sources[0].reference_id
