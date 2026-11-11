from test.agent_stream_fixtures import streaming_model
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
            assert set(facts['known_assets'][0]) == {'id', 'asset_type', 'canonical_name', 'aliases'}
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

    model = streaming_model(respond)
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
        assert counts == {'cast': 1, 'design': 2}  # One shared repair, as enforced at the model boundary.
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
    assert counts == {'cast': 1, 'design': 2}


def test_cast_scope_keeps_mentions_separate_and_preserves_placeholder_requirements():
    for language in ('zh', 'en'):
        text = render_cast_scope(language, {'characters': []}, ((1, '已登记占位'),))
        assert '已登记占位' in text
        assert 'required_asset_names' in text
        assert ('仅被提及' if language == 'zh' else 'Mention-only') in text


def test_chapter_inventory_keeps_visual_panels_out_of_characters_and_excludes_voice_only():
    source = '角色甲站在会议室。面前浮现半透明系统面板。脑中响起提示音。'
    cast = ChapterCast.model_validate({
        'characters': [{'name': '角色甲', 'presence': 'present', 'quote': '角色甲站在会议室。'},
                       {'name': '提示音', 'presence': 'voice_only', 'quote': '脑中响起提示音。'}],
        'scenes': [{'name': '会议室', 'presence': 'present', 'quote': '角色甲站在会议室。'}],
        'items': [{'name': '系统', 'presence': 'present', 'quote': '面前浮现半透明系统面板。'}],
    })
    validate_cast(cast, source, [{'id': 10, 'asset_type': 3, 'canonical_name': '系统', 'aliases': []}])
    assert cast.required_names() == ['角色甲']
    assert cast.required_assets() == [(1, '角色甲'), (2, '会议室'), (3, '系统')]
    assert cast.items[0].existing_asset_id == 10


@pytest.mark.parametrize('name', ['晨星', '旧称'])
def test_chapter_inventory_resolves_same_names_and_aliases_within_asset_category(name):
    entry = {'name': name, 'presence': 'present', 'quote': '晨星走进晨星站，拿起名为晨星的望远镜。'}
    cast = ChapterCast.model_validate({'characters': [entry], 'scenes': [entry], 'items': [entry]})
    registry = [{'id': kind, 'asset_type': kind, 'canonical_name': '晨星', 'aliases': ['旧称']} for kind in (1, 2, 3)]
    validate_cast(cast, entry['quote'], registry)
    assert [cast.characters[0].existing_asset_id, cast.scenes[0].existing_asset_id, cast.items[0].existing_asset_id] == [1, 2, 3]
    assert cast.required_assets() == [(1, '晨星'), (2, '晨星'), (3, '晨星')]


def test_new_person_may_share_a_name_with_an_existing_prop():
    cast = ChapterCast(characters=[{'name': '晨星', 'presence': 'present', 'quote': '晨星开门。'}])
    validate_cast(cast, '晨星开门。', [{'id': 3, 'asset_type': 3, 'canonical_name': '晨星'}])
    assert cast.characters[0].existing_asset_id is None
    assert cast.required_assets() == [(1, '晨星')]


def test_required_designs_never_substitute_another_asset_category_with_the_same_name():
    from services.extraction.extractor import AssetExtractionResult, Item, Person, validate_required_design_assets
    result = AssetExtractionResult(persons=[], scenes=[], items=[Item(name='晨星', base_traits='道具设计')])
    with pytest.raises(ValueError, match='人物/晨星'):
        validate_required_design_assets(result, ((1, '晨星'), (3, '晨星')))
    result.persons.append(Person(name='晨星', base_traits='人物设计'))
    validate_required_design_assets(result, ((1, '晨星'), (3, '晨星')))


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_inventory_instructions_cover_all_categories_and_preserve_the_visual_protocol(language):
    text = render_cast_instructions(language)
    assert all(field in text for field in ('characters', 'scenes', 'items', 'voice_only', 'quote'))
    assert ('quote' if language == 'zh' else 'exact source quote') in text
    assert ('不同类型资产允许同名' if language == 'zh' else 'Different asset categories may share a name') in text
    scope = render_cast_scope(language, {'characters': [], 'scenes': [], 'items': []}, ((3, '系统'),))
    assert '3=' in scope and '系统' in scope


@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_same_name_assets_of_all_categories_are_saved_independently(language):
    from models.asset import Asset
    from models.config import GeneralConfig
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project
    from test.test_services.test_asset_design_instructions import synthetic_snapshot, fixed_asset_prompt

    novel, chapter, _ = await enabled_project()
    chapter.content = '晨星来到晨星观测站，拿起代号晨星的望远镜。'
    await chapter.save()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': language})
    snapshot = synthetic_snapshot()
    calls = []
    def respond(messages, info):
        tool = info.output_tools[0]
        calls.append(tool.name)
        if 'characters' in tool.parameters_json_schema['properties']:
            entry = {'name': '晨星', 'presence': 'present', 'quote': chapter.content}
            payload = {field: [entry] for field in ('characters', 'scenes', 'items')}
        else:
            payload = {field: [{'name': '晨星', 'base_traits': fixed_asset_prompt(language, kind=kind, snapshot=snapshot)}]
                       for field, kind in [('persons', 'person'), ('scenes', 'scene'), ('items', 'item')]}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)])
    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await chapter_controller.extract(chapter.id)
        task.request_params['skill_snapshot'] = snapshot.model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    saved = await Asset.filter(novel=novel, canonical_name='晨星').order_by('asset_type')
    assert [asset.asset_type for asset in saved] == [1, 2, 3]
    assert len({asset.id for asset in saved}) == 3
    assert len(calls) == 2  # One inventory read and one design call, with no repair.


@pytest.mark.parametrize('field,asset_type', [('characters', 3), ('scenes', 1), ('items', 2)])
def test_chapter_inventory_rejects_registered_assets_in_the_wrong_category(field, asset_type):
    cast = ChapterCast.model_validate({'characters': [], field: [
        {'name': '对象', 'presence': 'present', 'quote': '对象出现。', 'existing_asset_id': 10}]})
    with pytest.raises(ValueError, match='category'):
        validate_cast(cast, '对象出现。', [{'id': 10, 'asset_type': asset_type, 'canonical_name': '对象', 'aliases': []}])


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('omit_visual_assets', [False, True])
async def test_extraction_persists_people_scenes_and_system_prop_without_false_character_failure(language, omit_visual_assets):
    from models.asset import Asset
    from models.config import GeneralConfig
    from models.agent_operation import AgentOperation
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project
    from test.test_services.test_asset_design_instructions import synthetic_snapshot, fixed_asset_prompt

    novel, chapter, _ = await enabled_project()
    chapter.content = '角色甲走入会议室，面前出现半透明系统面板。'
    await chapter.save()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': language})
    snapshot = synthetic_snapshot()
    counts = {'inventory': 0, 'design': 0}

    def respond(messages, info):
        tool = info.output_tools[0]
        if 'characters' in tool.parameters_json_schema['properties']:
            counts['inventory'] += 1
            assert 'scenes' in tool.parameters_json_schema['properties']
            assert 'items' in tool.parameters_json_schema['properties']
            payload = {
                'characters': [{'name': '角色甲', 'presence': 'present', 'quote': chapter.content}],
                'scenes': [{'name': '会议室', 'presence': 'present', 'quote': chapter.content}],
                'items': [{'name': '系统', 'presence': 'present', 'quote': chapter.content}],
            }
        else:
            counts['design'] += 1
            omit = omit_visual_assets and counts['design'] == 1
            payload = {
                'persons': [{'name': '角色甲', 'base_traits': fixed_asset_prompt(language, snapshot=snapshot)}] if counts['design'] == 1 else [],
                'scenes': [] if omit else [{'name': '会议室', 'base_traits': fixed_asset_prompt(language, kind='scene', snapshot=snapshot)}],
                'items': [] if omit else [{'name': '系统', 'base_traits': fixed_asset_prompt(language, kind='item', snapshot=snapshot)}],
            }
            if counts['design'] > 1:
                retry = next(part.content for message in reversed(messages) for part in message.parts if isinstance(part, RetryPromptPart))
                assert '会议室' in retry and '系统' in retry and '角色甲' in retry
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)])

    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await chapter_controller.extract(chapter.id)
        task.request_params['skill_snapshot'] = snapshot.model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assets = await Asset.filter(novel=novel).order_by('asset_type')
    assert [(a.asset_type, a.canonical_name) for a in assets] == [(1, '角色甲'), (2, '会议室'), (3, '系统')]
    assert all(a.base_traits and a.source_chapters == [chapter.number] for a in assets)
    assert counts == {'inventory': 1, 'design': 2 if omit_visual_assets else 1}
    checkpoint = await AgentOperation.get(task=task, key='candidate:assets:')
    assert not checkpoint.result['issues']
