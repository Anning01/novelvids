"""First-appearance facts are chronological, scoped and carried across batches."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from prompts.storyboard import build_storyboard_messages
from schemas.scene import SceneEntity, Storyboard
from services.storyboard.generator import generate_storyboard
from services.storyboard.strategies import storyboard_strategy_factory
from test.test_services.test_storyboard_handler import _shot


def person(name='张三', asset_id=None):
    return SceneEntity(name=name, aliases=['三哥'] if name == '张三' else [],
                       description='从蓝星穿越到古代的青年', asset_type='人物', asset_id=asset_id)


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('strategy', storyboard_strategy_factory.list(), ids=lambda strategy: strategy.key)
def test_introduction_requirement_is_shared_by_all_strategies_and_languages(language, strategy):
    messages = build_storyboard_messages('张三走进院子', [person()], language, strategy=strategy,
                                         previously_seen_assets=['李四'])
    system = messages[0]['content']
    assert ('根据昵称和描述' if language == 'zh' else 'from their nickname and description') in system
    assert '"nickname":"张三"' in system
    assert '从蓝星穿越到古代的青年' in system
    injected = system.split('\n')[-1]
    for constraint in ('人物旁', '横排', '竖排', '字体', '背景', '显示及消失时间', 'visual_prose', 'actions', '「'):
        assert constraint not in injected
    assert 'Character introduction text' not in injected


@pytest.mark.asyncio
async def test_previous_appearances_ignore_current_later_deleted_other_projects_and_voice_mentions():
    from services.storyboard.appearances import previously_seen_assets

    novel = await Novel.create(name='首次人物介绍')
    chapters = [await Chapter.create(novel_id=novel.id, number=i, name=str(i), content='正文') for i in (1, 2, 3)]
    other = await Novel.create(name='另一个项目')
    other_chapter = await Chapter.create(novel_id=other.id, number=1, name='1', content='正文')
    entities = []
    for index, name in enumerate(['张三', '本章人物', '后续人物', '删除分镜人物', '画外音人物', '别项目人物']):
        asset = await Asset.create(novel_id=novel.id, asset_type=1, canonical_name=name)
        entities.append(person(name, asset.id))
        chapter = chapters[1] if index == 1 else chapters[2] if index == 2 else other_chapter if index == 5 else chapters[0]
        scene = await Scene.create(chapter_id=chapter.id, sequence=index + 1,
                                   prompt_params={'visual_prose': '' if index == 4 else f'@{{{name}}}站在院中',
                                                  'dialogue': [f'0s-1s: @{{{name}}}：你好']})
        await scene.assets.add(asset)
        if index == 3:
            from tortoise.timezone import now
            await Scene.with_deleted().filter(id=scene.id).update(deleted_at=now())
    assert await previously_seen_assets(chapters[1], entities) == ['张三']
    # Regenerating the first chapter must not treat its old shots as prior appearances.
    assert await previously_seen_assets(chapters[0], entities) == []


@pytest.mark.asyncio
async def test_batches_carry_visible_characters_but_not_mentions():
    completion = SimpleNamespace(model='fake', id='fake', created=1, usage=None, choices=[])
    first = _shot(1, '三哥推门进来。')
    first.dialogue = ['0s-1s: @{张三}：李四在哪里？']
    calls = AsyncMock(side_effect=[(Storyboard(shots=[first]), completion),
                                   (Storyboard(shots=[_shot(2)]), completion)])
    with patch('services.storyboard.generator.create_json_completion', calls), patch(
        'services.storyboard.generator.NarrativeChunker.split', return_value=['上半章', '下半章']
    ):
        await generate_storyboard(None, '正文', [person(), person('李四')], 'fake', previously_seen_assets=['王五'])
    systems = [call.kwargs['messages'][0]['content'] for call in calls.await_args_list]
    assert '"nickname":"张三"' in systems[0] and '"nickname":"李四"' in systems[0]
    assert '"nickname":"李四"' in systems[1]
    assert '"nickname":"张三"' not in systems[1]


@pytest.mark.asyncio
async def test_empty_context_and_historical_relation_fallback_are_stable():
    from services.storyboard.appearances import previously_seen_assets

    novel = await Novel.create(name='旧分镜兼容')
    prior = await Chapter.create(novel_id=novel.id, number=1, name='1', content='正文')
    chapter = await Chapter.create(novel_id=novel.id, number=2, name='2', content='正文')
    assert await previously_seen_assets(chapter, []) == []
    asset = await Asset.create(novel_id=novel.id, asset_type=1, canonical_name='张三')
    scene = await Scene.create(chapter_id=prior.id, sequence=1, prompt='旧手写分镜', prompt_params={})
    await scene.assets.add(asset)
    entities = [person(asset_id=asset.id)]
    assert await previously_seen_assets(chapter, entities) == ['张三']
    assert await previously_seen_assets(chapter, entities) == ['张三']


@pytest.mark.asyncio
async def test_handler_loads_prior_appearances_into_generation_request():
    from services.storyboard.handler import StoryboardTaskHandler

    novel = await Novel.create(name='生成入口首次介绍')
    prior = await Chapter.create(novel_id=novel.id, number=1, name='1', content='正文')
    chapter = await Chapter.create(novel_id=novel.id, number=2, name='2', content='张三再次出现')
    asset = await Asset.create(novel_id=novel.id, asset_type=1, canonical_name='张三', source_chapters=[1, 2],
                               description='从蓝星穿越到古代', base_traits='外貌用的生图提示词')
    scene = await Scene.create(chapter_id=prior.id, sequence=1, prompt_params={'visual_prose': '三哥走进房间'})
    asset.aliases = ['三哥']
    await asset.save(update_fields=['aliases'])
    await scene.assets.add(asset)
    generate = AsyncMock(return_value=(Storyboard(shots=[]), {}))
    with patch('services.storyboard.handler.generate_storyboard', generate), patch(
        'services.storyboard.handler.AsyncOpenAI'
    ):
        await StoryboardTaskHandler().execute({'chapter_id': chapter.id, 'base_url': 'https://example.invalid',
                                              'api_key': 'test', 'model': 'fake'})
    assert generate.await_args.kwargs['previously_seen_assets'] == ['张三']
    assert generate.await_args.kwargs['introduction_descriptions'] == {'张三': '从蓝星穿越到古代'}


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['zh', 'en'])
async def test_model_chosen_introduction_is_preserved_through_serialization_and_storage(language):
    from test.test_services.test_storyboard_speech_timing import snapshot
    from schemas.agent_workflow import StructuredSkillStoryboard
    from services.creation_agent.skill_execution import current_execution
    from services.storyboard.handler import StoryboardTaskHandler
    from utils.prompt_language import skill_workflow

    name = '张三' if language == 'zh' else 'Zhang San'
    novel = await Novel.create(name='人物介绍保存' + language)
    chapter = await Chapter.create(novel_id=novel.id, number=1, name='1', content='正文')
    asset = await Asset.create(novel_id=novel.id, asset_type=1, canonical_name=name)
    entity = person(name, asset.id)
    shot = _shot(1, f'@{{{name}}} stands in the courtyard.')
    introduction = f'0s-2s: 旁白：{name}是从蓝星穿越而来的青年。' if language == 'zh' else f'0s-2s: Narrator: {name} is a time traveler.'
    shot.narration = [introduction]
    from schemas.scene import BlockingMap
    from test.test_services.test_scene_blueprint import SHOT, LAYOUT
    shot.blocking_map = BlockingMap.model_validate({**SHOT, 'layout':LAYOUT, 'assets':[*SHOT['assets'], {'name':name, 'x':40,'y':50}]})
    raw = StructuredSkillStoryboard.model_validate({'shots': [shot.model_dump()]})
    execution = SimpleNamespace(snapshot=snapshot(with_timing=False),
                                params={'assistant_model_config_id': 1}, generate=AsyncMock(return_value=raw))
    token = current_execution.set(execution)
    try:
        result, metadata = await generate_storyboard(None, '正文', [entity], 'fake', prompt_language=language,
                                                     storyboard_strategy='narration', previously_seen_assets=['王五'])
        requirement = execution.generate.await_args.kwargs['additional_instructions']
        assert name in requirement and '王五' not in requirement
    finally:
        current_execution.reset(token)
    token = skill_workflow.set(True)
    try:
        scenes = await StoryboardTaskHandler()._save_scenes(chapter.id, result, metadata, 0, language, [entity], 'narration')
    finally:
        skill_workflow.reset(token)
    scene = scenes[0]
    assert introduction in scene.prompt
    assert scene.prompt_params['narration'] == [introduction]
    await scene.fetch_related('assets')
    assert [asset.id for asset in scene.assets] == [entity.asset_id]


def test_visible_presence_tracks_props_and_internal_segments_but_not_spoken_mentions():
    from prompts.storyboard import visible_storyboard_assets

    prop = SceneEntity(name='旧钥匙', aliases=[], description='', asset_type='物品')
    shot = SimpleNamespace(visual_prose='@{旧钥匙}放在桌上',
                           dialogue=['0s-1s: 旁白：张三不在这里'],
                           segments=[{'visual_prose': '三哥走进屋内', 'actions': []}])
    assert visible_storyboard_assets(shot, [person(), prop]) == ['张三', '旧钥匙']
    shot.segments = [SimpleNamespace(visual_prose='@{张三}走进屋内', actions=[])]
    assert visible_storyboard_assets(shot, [person(), prop]) == ['张三', '旧钥匙']


@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('strategy', storyboard_strategy_factory.list(), ids=lambda strategy: strategy.key)
def test_no_new_characters_leave_original_generation_prompt_unchanged(language, strategy):
    from prompts.skill_pack import render_skill
    from prompts.asset_introductions import asset_introduction_requirement

    messages = build_storyboard_messages('张三再次出现', [person()], language, strategy=strategy,
                                         previously_seen_assets=['张三'])
    assert messages[0]['content'] == render_skill('storyboard', language)
    assert messages == build_storyboard_messages('张三再次出现', [person()], language, strategy=strategy,
                                                 previously_seen_assets=['张三', '李四'])
    assert 'previously_seen_assets' not in messages[1]['content']
    assert asset_introduction_requirement([], [], language) == ''
    assert '主体昵称' not in messages[0]['content']


@pytest.mark.asyncio
async def test_skill_generation_without_new_people_does_not_inject_instructions():
    from test.test_services.test_storyboard_speech_timing import snapshot
    from schemas.agent_workflow import StructuredSkillStoryboard
    from services.creation_agent.skill_execution import current_execution

    from test.test_services.test_scene_blueprint import SHOT, LAYOUT
    draft = {**_shot().model_dump(), 'blocking_map':{**SHOT, 'layout':LAYOUT,
             'assets':[*SHOT['assets'], {'name':'张三', 'x':40,'y':50}]}}
    execution = SimpleNamespace(snapshot=snapshot(with_timing=False), params={'assistant_model_config_id': 1},
        generate=AsyncMock(return_value=StructuredSkillStoryboard.model_validate({'shots':[draft]})))
    token = current_execution.set(execution)
    try:
        await generate_storyboard(None, '张三再次出现', [person()], 'fake', previously_seen_assets=['张三'])
        assert execution.generate.await_args.kwargs == {}
        assert 'previously_seen_assets' not in execution.generate.await_args.args[1]
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_later_batch_has_no_extra_prompt_once_all_characters_have_appeared():
    from prompts.skill_pack import render_skill

    completion = SimpleNamespace(model='fake', id='fake', created=1, usage=None, choices=[])
    calls = AsyncMock(return_value=(Storyboard(shots=[_shot()]), completion))
    with patch('services.storyboard.generator.create_json_completion', calls), patch(
        'services.storyboard.generator.NarrativeChunker.split', return_value=['张三初次出现', '张三再次出现']
    ):
        await generate_storyboard(None, '正文', [person()], 'fake')
    assert '"nickname":"张三"' in calls.await_args_list[0].kwargs['messages'][0]['content']
    assert calls.await_args_list[1].kwargs['messages'][0]['content'] == render_skill('storyboard', 'zh')


@pytest.mark.parametrize('asset_type', ['人物', '场景', '物品'])
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_introductions_use_nickname_and_description_for_every_asset_type(asset_type, language):
    from prompts.asset_introductions import asset_introduction_requirement

    entity = SceneEntity(name='主体昵称', aliases=[], asset_type=asset_type,
                         description='角色描述与外貌生图任务的组合')
    requirement = asset_introduction_requirement([entity], [], language, {'主体昵称': '实际资产描述'})
    assert json.dumps({'nickname': '主体昵称', 'description': '实际资产描述'}, ensure_ascii=False, separators=(',', ':')) in requirement
    assert '外貌生图任务' not in requirement
    assert asset_introduction_requirement([entity], ['主体昵称'], language, {'主体昵称': '实际资产描述'}) == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('asset_type', [1, 2, 3])
async def test_prior_appearances_are_loaded_for_people_locations_and_props(asset_type):
    from services.storyboard.appearances import previously_seen_assets

    novel = await Novel.create(name='三类主体出场')
    prior = await Chapter.create(novel_id=novel.id, number=1, name='1', content='正文')
    current = await Chapter.create(novel_id=novel.id, number=2, name='2', content='正文')
    asset = await Asset.create(novel_id=novel.id, asset_type=asset_type, canonical_name='主体')
    scene = await Scene.create(chapter_id=prior.id, sequence=1, prompt_params={'visual_prose': '@{主体}出现'})
    await scene.assets.add(asset)
    entity = SceneEntity(name='主体', aliases=[], description='描述', asset_id=asset.id,
                         asset_type={1: '人物', 2: '场景', 3: '物品'}[asset_type])
    assert await previously_seen_assets(current, [entity]) == ['主体']


def test_location_in_environment_counts_as_an_actual_appearance():
    from prompts.storyboard import visible_storyboard_assets

    location = SceneEntity(name='旧宅', aliases=[], description='张三的老家', asset_type='场景')
    shot = SimpleNamespace(environment='@{旧宅}内烛火摇曳', visual_prose='烛光映在墙上')
    assert visible_storyboard_assets(shot, [location]) == ['旧宅']
