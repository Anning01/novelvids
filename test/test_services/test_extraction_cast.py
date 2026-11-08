import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, RetryPromptPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from services.extraction.cast import ChapterCast, validate_cast
from prompts.extraction import render_cast_instructions, render_cast_scope


def test_cast_distinguishes_presence_and_resolves_existing_aliases():
    content = '阿洛推门。回忆里，老周挥手。有人提及张三。'
    cast = ChapterCast(characters=[
        {'name': '阿洛', 'presence': 'present', 'quote': '阿洛推门。'},
        {'name': '老周', 'presence': 'flashback', 'quote': '回忆里，老周挥手。'},
        {'name': '张三', 'presence': 'mentioned', 'quote': '有人提及张三。'},
    ])
    validate_cast(cast, content, [{'id': 10, 'canonical_name': '陈洛', 'aliases': ['阿洛']}])
    assert cast.required_names() == ['陈洛', '老周']
    assert cast.characters[0].existing_asset_id == 10


@pytest.mark.parametrize('changes', [{'quote': '编造原文'}, {'existing_asset_id': 999}, {'name': ' '}])
def test_cast_rejects_unfounded_evidence_and_foreign_ids(changes):
    cast = ChapterCast(characters=[{'name': '陈洛', 'presence': 'present', 'quote': '陈洛推门。', **changes}])
    with pytest.raises(ValueError):
        validate_cast(cast, '陈洛推门。', [])


def test_shared_title_does_not_merge_distinct_people():
    cast = ChapterCast(characters=[{'name': '师父', 'presence': 'present', 'quote': '师父说话。'}])
    with pytest.raises(ValueError, match='multiple identities'):
        validate_cast(cast, '师父说话。', [{'id': i, 'canonical_name': str(i), 'aliases': ['师父']} for i in (1, 2)])


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('complete_new_character', [True, False])
async def test_new_unregistered_character_is_required_and_only_omission_is_repaired(language, complete_new_character):
    from models.asset import Asset
    from models.config import GeneralConfig
    from models.agent_operation import AgentOperation
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project
    from test.test_services.test_asset_design_instructions import synthetic_snapshot, fixed_asset_prompt

    novel, chapter, _ = await enabled_project()
    chapter.content = '阿洛推门。小梅说：“进来。”回忆里，老周挥手。有人提及张三。'
    await chapter.save()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': language})
    snapshot = synthetic_snapshot()
    prompt = fixed_asset_prompt(language, snapshot=snapshot)
    await Asset.create(novel=novel, asset_type=1, canonical_name='陈洛', aliases=['阿洛'], base_traits=prompt, source_chapters=[1])
    counts = {'cast': 0, 'design': 0}

    def respond(messages, info):
        tool = info.output_tools[0]
        if 'characters' in tool.parameters_json_schema['properties']:
            counts['cast'] += 1
            facts = next(json.loads(part.content)['untrusted_task_facts']['input'] for message in messages
                         for part in message.parts if isinstance(part, UserPromptPart))
            assert facts['chapter']['content'] == chapter.content
            assert set(facts['known_characters'][0]) == {'id', 'canonical_name', 'aliases'}
            assert render_cast_instructions(language) in info.instructions
            payload = {'characters': [
                {'name': '阿洛', 'presence': 'present', 'quote': '阿洛推门。'},
                {'name': '小梅', 'presence': 'present', 'quote': '小梅说：“进来。”'},
                {'name': '老周', 'presence': 'flashback', 'quote': '回忆里，老周挥手。'},
                {'name': '张三', 'presence': 'mentioned', 'quote': '有人提及张三。'},
            ]}
        else:
            counts['design'] += 1
            if counts['design'] == 1:
                names = ['陈洛', '老周']
                assert '小梅' in str(messages)
            else:
                retry = next(part.content for message in reversed(messages) for part in message.parts if isinstance(part, RetryPromptPart))
                assert '小梅' in retry
                names = ['小梅'] if complete_new_character else []
            payload = {'persons': [{'name': name, 'base_traits': prompt} for name in names], 'scenes': [], 'items': []}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)])

    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await chapter_controller.extract(chapter.id)
        task.request_params['skill_snapshot'] = snapshot.model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    if complete_new_character:
        assert task.status == 3, task.error_message
        assert counts == {'cast': 1, 'design': 2}
        assert set(await Asset.filter(novel=novel).values_list('canonical_name', flat=True)) == {'陈洛', '小梅', '老周'}
        assert (await Asset.get(novel=novel, canonical_name='小梅')).source_chapters == [1]
    else:
        assert task.status == 4
        assert '小梅' in task.error_message
        assert counts == {'cast': 1, 'design': 3}
        assert set(await Asset.filter(novel=novel).values_list('canonical_name', flat=True)) == {'陈洛'}
        checkpoint = await AgentOperation.get(task=task, key='candidate:assets:')
        assert {item['name'] for item in checkpoint.result['accepted']['persons']} == {'陈洛', '老周'}
    roster = await AgentOperation.filter(task=task, key__startswith='model:structured:ChapterCast:').get()
    assert roster.state == 'completed'
    assert len(roster.result['characters']) == 4
    # Resume the same read from its receipt, without another model invocation.
    from services.creation_agent.skill_execution import SkillExecution
    from services.extraction.cast import read_chapter_cast
    from services.extraction.context import ExtractionContextLoader
    from services.extraction.messages import ExtractionMessageBuilder
    from models.creation_agent import AgentMessage
    context = await ExtractionContextLoader().load(novel_id=novel.id, chapter_id=chapter.id)
    execution = SkillExecution({**task.request_params, 'task_id': str(task.id)},
        await AgentMessage.get(task=task, role='assistant'), AsyncMock())
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        replay = await read_chapter_cast(execution, ExtractionMessageBuilder().build(context, language))
    assert replay.required_names() == ['陈洛', '小梅', '老周']
    assert counts == {'cast': 1, 'design': 2 if complete_new_character else 3}


def test_cast_scope_keeps_mentions_separate_and_preserves_placeholder_requirements():
    for language in ('zh', 'en'):
        text = render_cast_scope(language, {'characters': []}, ((1, '已登记占位'),))
        assert '已登记占位' in text
        assert 'required_asset_names' in text
        assert ('仅被提及' if language == 'zh' else 'Mention-only') in text
