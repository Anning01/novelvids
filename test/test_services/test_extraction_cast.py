from test.agent_stream_fixtures import streaming_model
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart

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
async def test_full_extraction_uses_the_screenplay_without_a_required_inventory(language):
    from models.asset import Asset
    from models.config import GeneralConfig
    from models.agent_operation import AgentOperation
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project
    from test.test_services.test_asset_design_instructions import synthetic_snapshot, fixed_asset_prompt

    novel, chapter, _ = await enabled_project()
    chapter.content = '文静（妻子、小静、儿媳）推门。建平在次卧应了一声。'
    await chapter.save()
    await GeneralConfig.update_or_create(id=1, defaults={'prompt_language': language})
    snapshot = synthetic_snapshot()
    prompt = fixed_asset_prompt(language, snapshot=snapshot)
    scene_prompt = ('次卧正面用暖橙光，反向机位用冷蓝光。' if language == 'zh'
                    else 'The bedroom front view uses amber light, and the reverse view uses blue light.')
    calls = []

    def respond(messages, info):
        tool = info.output_tools[0]
        calls.append(tool.name)
        assert 'persons' in tool.parameters_json_schema['properties']
        assert chapter.content in str(messages)
        assert 'required_asset_names' not in str(messages)
        return ModelResponse(parts=[ToolCallPart(tool.name, {
            'persons': [{'name': '文静', 'aliases': ['妻子', '小静', '儿媳'], 'base_traits': prompt}],
            'scenes': [{'name': '次卧', 'base_traits': scene_prompt}], 'items': [],
        })])

    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await chapter_controller.extract(chapter.id)
        task.request_params['skill_snapshot'] = snapshot.model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(calls) == 1
    assert not await AgentOperation.filter(task=task, key__startswith='model:structured:ChapterCast:').exists()
    asset = await Asset.get(novel=novel, canonical_name='文静')
    assert asset.aliases == ['妻子', '小静', '儿媳']
    assert asset.source_chapters == [chapter.number]
    assert (await Asset.get(novel=novel, canonical_name='次卧')).base_traits == scene_prompt


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
    assert len(calls) == 1


@pytest.mark.parametrize('field,asset_type', [('characters', 3), ('scenes', 1), ('items', 2)])
def test_chapter_inventory_rejects_registered_assets_in_the_wrong_category(field, asset_type):
    cast = ChapterCast.model_validate({'characters': [], field: [
        {'name': '对象', 'presence': 'present', 'quote': '对象出现。', 'existing_asset_id': 10}]})
    with pytest.raises(ValueError, match='category'):
        validate_cast(cast, '对象出现。', [{'id': 10, 'asset_type': asset_type, 'canonical_name': '对象', 'aliases': []}])


@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_extraction_persists_people_scenes_and_system_prop_without_false_character_failure(language):
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
    def respond(messages, info):
        tool = info.output_tools[0]
        payload = {
            'persons': [{'name': '角色甲', 'base_traits': fixed_asset_prompt(language, snapshot=snapshot)}],
            'scenes': [{'name': '会议室', 'base_traits': fixed_asset_prompt(language, kind='scene', snapshot=snapshot)}],
            'items': [{'name': '系统', 'base_traits': fixed_asset_prompt(language, kind='item', snapshot=snapshot)}],
        }
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
    checkpoint = await AgentOperation.get(task=task, key='candidate:assets:')
    assert not checkpoint.result['issues']


@pytest.mark.asyncio
async def test_asset_workflow_persists_complete_chapter_after_truncation(monkeypatch):
    from models.asset import Asset
    from models.agent_operation import AgentOperation
    from services.creation_agent.model_boundary import ModelOutputLimitError
    from services.creation_agent.skill_execution import SkillExecution
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from test.test_services.test_skill_workflow import enabled_project
    from test.test_services.test_asset_design_instructions import fixed_asset_prompt, synthetic_snapshot

    novel, chapter, _ = await enabled_project()
    chapter.content = '甲推门。乙回头。'
    await chapter.save()
    snapshot = synthetic_snapshot()
    original = SkillExecution._generate

    async def truncate(self, skill, facts, output_type, **options):
        if skill == 'assets' and isinstance(facts, list):
            raise ModelOutputLimitError('length')
        if skill == 'structured' and facts['chapter']['content'] == chapter.content:
            raise ModelOutputLimitError('length')
        return await original(self, skill, facts, output_type, **options)

    def respond(messages, info):
        tool = info.output_tools[0]
        if 'characters' in tool.parameters_json_schema['properties']:
            text = str(messages[-1].parts[0].content)
            name = '甲' if '甲推门' in text else '乙'
            payload = {'characters': [{'name': name, 'presence': 'present', 'quote': name}]}
        else:
            import json
            facts = json.loads(messages[-1].parts[0].content)['untrusted_task_facts']['input']
            name = facts['selection']['name']
            payload = {'persons': [{'name': name, 'base_traits': fixed_asset_prompt('en', snapshot=snapshot)}],
                       'items': [], 'scenes': []}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)])

    monkeypatch.setattr(SkillExecution, '_generate', truncate)
    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        task = await chapter_controller.extract(chapter.id)
        task.request_params['skill_snapshot'] = snapshot.model_dump()
        await task.save()
        await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert await Asset.filter(novel=novel, canonical_name__in=['甲', '乙']).count() == 2
    assert await AgentOperation.filter(task=task, state='completed', key__startswith='model:assets:AssetExtractionResult:entry:').count() == 2


@pytest.mark.parametrize('language,phrase', [('zh', '一个资产'), ('en', 'one asset')])
def test_single_asset_recovery_supports_queued_skill_snapshots(language, phrase):
    import json
    from prompts.extraction import single_asset_instructions
    from prompts.skill_pack import snapshot_skills, use_skill_snapshot
    snapshot = snapshot_skills()
    old = json.loads(snapshot['contents']['asset_templates'])
    old.pop('single_asset')
    snapshot['contents']['asset_templates'] = json.dumps(old)
    with use_skill_snapshot(snapshot):
        assert phrase in single_asset_instructions(language)


@pytest.mark.asyncio
async def test_new_run_reuses_completed_entries_after_provider_rejection(monkeypatch):
    from pydantic_ai.exceptions import ModelHTTPError
    from models.asset import Asset
    from controllers.chapter import chapter_controller
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.model_boundary import ModelOutputLimitError
    from services.creation_agent.skill_execution import SkillExecution
    from test.test_services.test_skill_workflow import enabled_project
    from test.test_services.test_asset_design_instructions import fixed_asset_prompt, synthetic_snapshot

    novel, chapter, _ = await enabled_project()
    chapter.content = '甲和乙走进书房。'
    await chapter.save()
    snapshot = synthetic_snapshot()
    calls = []
    original = SkillExecution._generate

    async def simulate(self, skill, facts, output_type, **options):
        if skill == 'assets' and isinstance(facts, list):
            calls.append('whole')
            from models.agent_operation import AgentOperation
            from services.creation_agent.plan_sources import fingerprint
            revision = fingerprint([skill, facts, self.snapshot.revision, self.language,
                self.params['assistant_model_config_id'], output_type.model_json_schema(), ''])
            await AgentOperation.create(task_id=self.params['task_id'], key='recovery:failure', state='completed',
                result={'issues': [{'code':'output_length'}]})
            await AgentOperation.create(task_id=self.params['task_id'], key='model-input:' + fingerprint('model:assets:AssetExtractionResult:'),
                state='completed', result={'revision': revision})
            raise ModelOutputLimitError('length')
        if skill == 'assets':
            name = facts['selection']['name']
            calls.append(name)
            if name == '乙' and calls.count(name) == 1:
                raise ModelHTTPError(402, 'test')
        return await original(self, skill, facts, output_type, **options)

    def respond(messages, info):
        tool = info.output_tools[0]
        if 'characters' in tool.parameters_json_schema['properties']:
            payload = {'characters': [{'name': n, 'presence': 'present', 'quote': n} for n in ('甲', '乙')]}
        else:
            payload = {'persons': [{'name': calls[-1], 'base_traits': fixed_asset_prompt('en', snapshot=snapshot)}],
                       'items': [], 'scenes': []}
        return ModelResponse(parts=[ToolCallPart(tool.name, payload)])

    monkeypatch.setattr(SkillExecution, '_generate', simulate)
    model = streaming_model(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        for expected in (4, 3):
            task = await chapter_controller.extract(chapter.id)
            task.request_params['skill_snapshot'] = snapshot.model_dump()
            await task.save()
            await ai_task_executor.run(task)
            await task.refresh_from_db()
            assert task.status == expected, task.error_message
    assert calls == ['whole', '甲', '乙', '乙']
    assert await Asset.filter(novel=novel, canonical_name__in=['甲', '乙']).count() == 2
