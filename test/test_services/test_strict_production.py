from unittest.mock import AsyncMock, Mock

import pytest

from models.asset import Asset
from models.chapter import Chapter
from models.config import AiModelConfig, GeneralConfig
from models.novel import Novel
from models.scene import Scene
from controllers.chapter import chapter_controller
from controllers.scene import scene_controller
from services.ai_task_executor import ai_task_executor
from services.creation_agent.skill_execution import SkillExecution
from test.test_services.test_strict_text_tasks import mock_model


@pytest.fixture
async def project(monkeypatch):
    monkeypatch.setattr('config.settings.AUTH_ENABLED', False)
    await GeneralConfig.create(id=1, prompt_language='zh')
    model = await AiModelConfig.create(name='strict-production', model='strict-model', task_type=7,
        base_url='https://model.invalid/v1', api_key='test', is_active=True,
        supports_json_output=True, supports_strict_output=True)
    novel = await Novel.create(name='渡口', episodes_managed=True, shot_duration_max=15)
    chapter = await Chapter.create(novel=novel, number=1, name='夜渡', content='原文',
        screenplay='1-1 渡口 外 夜\n出场：阿岚\n△ 阿岚提灯停下。\n阿岚：等一等。')
    return novel, chapter, model


def asset_payload():
    import json
    from prompts.skill_pack import read_skill
    fields = json.loads(read_skill('asset_contract'))['zh']['person']['fields']
    return {'persons': [{'name': '阿岚', 'aliases': [], 'label': '人物', 'description': '渡口来客',
        'design': '黑发少女，穿青色布衣。', 'visual_fields': {key: '具体设计' for key in fields}, 'variant': None}],
        'scenes': [], 'items': []}


def shot_payload():
    fields = ('description', 'shot_size_and_camera', 'visual_style', 'time_setting', 'environment',
        'spatial_relationships', 'visual_prose', 'format_and_look', 'lenses_and_filtration',
        'lighting_and_atmosphere', 'grade_and_palette', 'camera_movement', 'sound_design', 'transition')
    return {'shots': [{**{key: '夜色下，阿岚在渡口提灯停下。' for key in fields}, 'duration': 4,
        'effect_restrictions': ['自然光'], 'allowed_effects': [], 'visible_asset_names': ['阿岚'],
        'actions': [{'start': 0, 'end': 4, 'text': '阿岚提灯停下。'}],
        'dialogue': [{'start': 1, 'end': 3, 'speaker': '阿岚', 'delivery': '急切', 'text': '等一等。'}],
        'narration': [], 'source_scene_number': '1-1', 'duration_split_part': None,
        'segments': [], 'blocking_map': None}]}


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', ['variant', 'design', 'visual_fields'])
async def test_asset_conversion_failure_explains_missing_field_without_retry(project, monkeypatch, missing):
    novel, chapter, _ = project
    payload = asset_payload()
    del payload['persons'][0][missing]
    requests = mock_model(monkeypatch, payload)
    task = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    assert task.error_message == f'资产结果转换失败：persons[0] 缺少字段 {missing}，尚未保存本次提取结果。'
    assert len(requests) == 1
    assert not await Asset.filter(novel=novel).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('task_kind', ['assets', 'storyboard'])
@pytest.mark.parametrize('text_api', ['chat_completions', 'responses'])
async def test_production_uses_one_strict_request_without_candidate_checks(project, monkeypatch, task_kind, text_api):
    novel, chapter, model = project
    model.text_api = text_api
    await model.save()
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, base_traits='人工确认的设定', source_chapters=[1])
    requests = mock_model(monkeypatch, asset_payload() if task_kind == 'assets' else shot_payload())
    forbidden = AsyncMock(side_effect=AssertionError('legacy generation or review must not run'))
    monkeypatch.setattr(SkillExecution, 'generate', forbidden)
    monkeypatch.setattr('services.creation_agent.direct_plan.prepare_direct_plan', forbidden)
    monkeypatch.setattr('services.creation_agent.creative_checks.generate_checked', forbidden)
    # Resolve module-level aliases before temporarily replacing their source functions.
    import services.creation_agent.prompt_edits
    import services.creation_agent.operations
    for target in ('services.storyboard.candidates.StoryboardCandidateValidator.merge',
        'services.storyboard.validation.validate_skill_storyboard_shot',
        'services.storyboard.validation.validate_skill_storyboard_timing',
        'services.creation_agent.prompt_edits.validate_prompt_dependencies'):
        monkeypatch.setattr(target, Mock(side_effect=AssertionError('no repeated format validation')))
    task = (await chapter_controller.extract(chapter.id) if task_kind == 'assets'
            else await scene_controller.generate(chapter.id))
    assert task.request_params['output_contract']['name'] == task_kind
    assert 'skill_snapshot' not in task.request_params
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    expected = {'type': 'json_schema', 'json_schema': {'name': task_kind,
        'schema': task.request_params['output_contract']['schema'], 'strict': True}}
    if text_api == 'responses':
        assert requests[0]['text']['format'] == {'type': 'json_schema', **expected['json_schema']}
    else:
        assert requests[0]['response_format'] == expected
    assert not requests[0].get('tools')
    forbidden.assert_not_awaited()
    if task_kind == 'assets':
        assert await Asset.filter(novel=novel).count() == 1
        assert (await Asset.get(novel=novel)).base_traits == '人工确认的设定'
    else:
        scene = await Scene.get(chapter=chapter)
        assert scene.duration == 4 and '1s-3s:' in scene.prompt and '等一等。' in scene.prompt
        assert await scene.assets.all().count() == 1


@pytest.mark.asyncio
async def test_asset_design_fields_are_rendered_once_and_variants_are_reused(project, monkeypatch):
    from models.asset_variant import AssetVariant
    novel, chapter, _ = project
    payload = asset_payload()
    person = payload['persons'][0]
    person['variant'] = {'existing_variant_id': None, 'name': '雨衣', 'description': '雨夜形态',
        'change_reason': '披上雨衣', 'design': '身穿蓝色雨衣', 'visual_fields': person['visual_fields']}
    requests = mock_model(monkeypatch, payload)
    first = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(first)
    await first.refresh_from_db()
    assert first.status == 3, first.error_message
    asset = await Asset.get(novel=novel)
    variant = await AssetVariant.get(asset=asset)
    assert '黑发少女' in asset.base_traits and '**时代基底**' in asset.base_traits
    assert '蓝色雨衣' in variant.base_traits
    await Asset.filter(id=asset.id).update(metadata={**asset.metadata, 'voice_reference_id': 123}, base_traits='人工定稿')
    person['variant']['existing_variant_id'] = variant.id
    second = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(second)
    await second.refresh_from_db()
    await asset.refresh_from_db()
    assert second.status == 3, second.error_message
    assert len(requests) == 2 and await AssetVariant.filter(asset=asset).count() == 1
    assert asset.base_traits == '人工定稿' and asset.metadata['voice_reference_id'] == 123


@pytest.mark.asyncio
async def test_extraction_reports_removed_settings_together_and_reuses_them_after_restore(project, monkeypatch):
    from services.creation_objects import CreationObjects, project_write

    novel, chapter, _ = project
    objects = CreationObjects(novel.id)
    archived = [
        await Asset.create(novel=novel, canonical_name=name, asset_type=1,
            base_traits='人工定稿', main_image='/media/approved.png', source_chapters=[2])
        for name in ('阿岚', '老周')
    ]
    other_novel = await Novel.create(name='另一作品')
    foreign = await Asset.create(novel=other_novel, canonical_name='路人', asset_type=1)
    other_type = await Asset.create(novel=novel, canonical_name='路人', asset_type=2)
    async with project_write(novel.id):
        for asset in [*archived, other_type]:
            await objects.archive('asset', asset.id)
    async with project_write(other_novel.id):
        await CreationObjects(other_novel.id).archive('asset', foreign.id)

    payload = asset_payload()
    person = payload['persons'][0]
    payload['persons'] = [{**person, 'name': name} for name in ('路人', '阿岚', '老周')]
    mock_model(monkeypatch, payload)
    failed = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(failed)
    await failed.refresh_from_db()

    assert failed.status == 4
    assert failed.error_message == '本章提取到已移除的同名设定（阿岚、老周）。请恢复这些设定后重新提取。'
    assert not await Asset.filter(novel=novel).exists()

    async with project_write(novel.id):
        for asset in archived:
            await objects.restore('asset', asset.id)
    retried = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(retried)
    await retried.refresh_from_db()

    assert retried.status == 3, retried.error_message
    assert await Asset.filter(novel=novel, asset_type=1).count() == 3
    for asset in archived:
        restored = await Asset.get(id=asset.id)
        assert restored.source_chapters == [1, 2]
        assert restored.base_traits == '人工定稿'
        assert restored.main_image == '/media/approved.png'


@pytest.mark.asyncio
async def test_foreign_variant_rolls_back_the_whole_asset_write(project, monkeypatch):
    from models.asset_variant import AssetVariant
    novel, chapter, _ = project
    other = await Novel.create(name='另一作品')
    foreign = await Asset.create(novel=other, canonical_name='另一人', asset_type=1)
    variant = await AssetVariant.create(asset=foreign, name='雨衣')
    payload = asset_payload()
    payload['persons'][0]['variant'] = {'existing_variant_id': variant.id, 'name': '雨衣', 'description': '',
        'change_reason': '换装', 'design': '雨衣', 'visual_fields': payload['persons'][0]['visual_fields']}
    requests = mock_model(monkeypatch, payload)
    task = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4 and len(requests) == 1
    assert not await Asset.filter(novel=novel).exists()
    assert await AssetVariant.filter(id=variant.id, asset=foreign).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['assets', 'storyboard'])
async def test_source_conflict_keeps_saved_results(project, monkeypatch, operation):
    novel, chapter, _ = project
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, base_traits='已保存', source_chapters=[1])
    old_scene = await Scene.create(chapter=chapter, sequence=1, prompt='人工分镜', description='原镜头')
    mock_model(monkeypatch, asset_payload() if operation == 'assets' else shot_payload())
    original = SkillExecution.generate_strict
    async def edit_source(self, facts):
        result = await original(self, facts)
        await Chapter.filter(id=chapter.id).update(screenplay='用户刚修改的导演稿')
        return result
    monkeypatch.setattr(SkillExecution, 'generate_strict', edit_source)
    task = await chapter_controller.extract(chapter.id) if operation == 'assets' else await scene_controller.generate(chapter.id, replace_existing=True)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    assert (await Scene.get(id=old_scene.id)).prompt == '人工分镜'
    assert (await Asset.get(novel=novel)).base_traits == '已保存'


@pytest.mark.asyncio
async def test_storyboard_includes_blocking_and_segments_without_extra_model_calls(project, monkeypatch):
    novel, chapter, _ = project
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[1])
    payload = shot_payload()
    shot = payload['shots'][0]
    shot['segments'] = [{key: shot[key] for key in ('description', 'shot_size_and_camera', 'visual_prose', 'camera_movement')} |
                        {'duration': 2, 'actions': ['阿岚停下。']} for _ in range(2)]
    shot['blocking_map'] = {'orientation': '上北', 'layout': None, 'axis': None,
        'assets': [{'x': 50, 'y': 50, 'name': '阿岚', 'asset_name': '阿岚', 'end': None,
                    'facing': '北', 'kind': 'person', 'heading': 0, 'route': []}],
        'cameras': [{'x': 50, 'y': 90, 'target': '阿岚', 'frame': {'left': {'x': 30, 'y': 40}, 'right': {'x': 70, 'y': 40}},
                     'framing': '中景', 'beat': '停下'}]}
    requests = mock_model(monkeypatch, payload)
    monkeypatch.setattr('services.storyboard.blocking_plans.place_shot', AsyncMock(side_effect=AssertionError('no second model request')))
    task = await scene_controller.generate(chapter.id, generate_blocking_maps=True)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    scene = await Scene.get(chapter=chapter)
    assert len(requests) == 1
    assert scene.prompt_params['blocking_map']['cameras'][0]['frame'][0]['x'] == 30
    assert len(scene.prompt_params['segments']) == 2 and '镜头2' in scene.prompt


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['assets', 'storyboard'])
async def test_production_uses_personal_skill_without_changing_protocol(project, monkeypatch, operation):
    from schemas.user_skill import UserSkillInput
    from services.user_skills import save_skill, set_default
    from fastapi import HTTPException
    novel, chapter, _ = project
    skill = await save_skill(0, UserSkillInput(task=operation, name='个性化创作', instructions='采用克制的复古电影风格。'))
    await set_default(0, operation, skill['id'])
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[1])
    requests = mock_model(monkeypatch, asset_payload() if operation == 'assets' else shot_payload())
    submit = chapter_controller.extract if operation == 'assets' else scene_controller.generate
    task = await submit(chapter.id)
    assert task.request_params['creative_method']['id'] == skill['id']
    with pytest.raises(HTTPException) as conflict:
        await submit(chapter.id, skill_id=0)
    assert conflict.value.status_code == 409
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert '采用克制的复古电影风格' in str(requests[0]['messages'])
    assert '先产出全套候选并通过校验' not in str(requests[0]['messages'])


@pytest.mark.asyncio
async def test_existing_storyboard_is_preserved_unless_replacement_was_requested(project, monkeypatch):
    _, chapter, _ = project
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='手工分镜')
    generator = AsyncMock(side_effect=AssertionError('must not append duplicates'))
    monkeypatch.setattr(SkillExecution, 'generate_strict', generator)
    task = await scene_controller.generate(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3 and task.response_data['preserved_existing'] is True
    assert task.response_data['scene_ids'] == [scene.id]
    generator.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_manual_shot_during_generation_is_not_overwritten(project, monkeypatch):
    novel, chapter, _ = project
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[1])
    mock_model(monkeypatch, shot_payload())
    original = SkillExecution.generate_strict
    async def manual_edit(self, facts):
        result = await original(self, facts)
        await Scene.create(chapter=chapter, sequence=1, prompt='刚添加的手工分镜')
        return result
    monkeypatch.setattr(SkillExecution, 'generate_strict', manual_edit)
    task = await scene_controller.generate(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4 and await Scene.filter(chapter=chapter).count() == 1
    assert (await Scene.get(chapter=chapter)).prompt == '刚添加的手工分镜'


@pytest.mark.asyncio
async def test_optional_storyboard_sheets_remain_separate_media_tasks(project, monkeypatch):
    from models.ai_task import AiTask
    novel, chapter, _ = project
    novel.storyboard_enabled = True
    await novel.save()
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[1])
    model = await AiModelConfig.create(name='sheet-images', model='gpt-image', task_type=2, image_model_type='gpt_image_2',
        base_url='https://image.invalid/v1', api_key='test', is_active=True)
    requests = mock_model(monkeypatch, shot_payload())
    task = await scene_controller.generate(chapter.id, sheet_model_config_id=model.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1 and len(task.response_data['storyboard_sheet_task_ids']) == 1
    media = await AiTask.get(id=task.response_data['storyboard_sheet_task_ids'][0])
    assert media.request_params['execution_mode'] == 'media'
    assert 'skill_snapshot' not in media.request_params


@pytest.mark.asyncio
async def test_speaking_character_uses_normal_asset_binding_without_another_model_call(project, monkeypatch):
    novel, chapter, _ = project
    hero = await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[1])
    speaker = await Asset.create(novel=novel, canonical_name='王叔', asset_type=1, source_chapters=[1],
        metadata={'voice_reference_id': 12})
    payload = shot_payload()
    payload['shots'][0]['dialogue'][0].update(speaker='王叔', delivery='画外呼喊', text='阿岚！')
    requests = mock_model(monkeypatch, payload)
    task = await scene_controller.generate(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    scene = await Scene.get(chapter=chapter)
    assert set(await scene.assets.all().values_list('id', flat=True)) == {hero.id, speaker.id}
    assert '角色参考：@{阿岚}、@{王叔}' in scene.prompt
    assert '@{王叔}（画外呼喊）: 阿岚！' in scene.prompt
    assert (await scene.assets.all().get(id=speaker.id)).metadata['voice_reference_id'] == 12
    assert len(requests) == 1
    assert '发声角色也属于角色引用' in str(requests[0]['messages'])


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_asset_wire_schema_has_no_empty_objects(language):
    import json
    from prompts.skill_pack import read_skill
    from schemas.text_task_contracts import output_contract
    specifications = json.loads(read_skill('asset_contract'))[language]
    schema = output_contract('assets', asset_specifications=specifications)['schema']
    def check(value):
        if isinstance(value, dict):
            if value.get('type') == 'object':
                assert value.get('properties'), 'Provider rejects object schemas without properties'
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)
    check(schema)
    scene = schema['properties']['scenes']['items']['properties']
    assert scene['visual_fields'] == {'type': 'null'}
    assert scene['variant']['anyOf'][0]['properties']['visual_fields'] == {'type': 'null'}


@pytest.mark.asyncio
async def test_scene_and_variant_with_no_visual_columns_save_via_responses(project, monkeypatch):
    from models.asset_variant import AssetVariant
    novel, chapter, model = project
    model.text_api = 'responses'
    await model.save()
    payload = {'persons': [], 'items': [], 'scenes': [{
        'name': '渡口', 'aliases': [], 'description': '故事发生地', 'design': '河岸木制渡口。', 'visual_fields': None,
        'variant': {'existing_variant_id': None, 'name': '暴雨后', 'description': '雨后场景',
                    'change_reason': '暴雨淹没河岸', 'design': '雨后被淹的渡口。', 'visual_fields': None},
    }]}
    requests = mock_model(monkeypatch, payload)
    task = await chapter_controller.extract(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    schema = requests[0]['text']['format']['schema']
    assert requests[0]['text']['format']['strict'] is True
    assert schema['properties']['scenes']['items']['properties']['visual_fields'] == {'type': 'null'}
    scene = await Asset.get(novel=novel, canonical_name='渡口')
    assert '河岸木制渡口。' in scene.base_traits
    assert '雨后被淹的渡口。' in (await AssetVariant.get(asset=scene)).base_traits


@pytest.mark.asyncio
@pytest.mark.parametrize('text_api', ['chat_completions', 'responses'])
async def test_storyboard_input_and_enum_share_only_current_chapter_candidates(project, monkeypatch, text_api):
    import json
    from models.asset_variant import AssetVariant
    novel, chapter, model = project
    model.text_api = text_api
    await model.save()
    hero = await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[1, 2])
    await Asset.create(novel=novel, canonical_name='其他章节', asset_type=1, source_chapters=[2], is_global=True)
    await Asset.create(novel=novel, canonical_name='未关联资产', asset_type=3, source_chapters=[], is_global=True)
    await AssetVariant.create(asset=hero, name='本章形态', chapter_numbers=[1])
    await AssetVariant.create(asset=hero, name='第二章形态', chapter_numbers=[2])
    await AssetVariant.create(asset=hero, name='未关联形态', chapter_numbers=[])
    requests = mock_model(monkeypatch, shot_payload())
    task = await scene_controller.generate(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    assert len(requests) == 1
    request = requests[0]
    messages = request.get('messages') or request['input']
    user = next(message for message in messages if message['role'] == 'user')['content']
    if isinstance(user, list):
        user = user[0]['text']
    context = json.loads(user)['task_context']['input']
    names = [entity['name'] for entity in context['entities']]
    assert names == ['阿岚', '阿岚#本章形态']
    schema = (request['text']['format']['schema'] if text_api == 'responses'
              else request['response_format']['json_schema']['schema'])
    fields = schema['properties']['shots']['items']['properties']
    assert fields['visible_asset_names']['items']['enum'] == names
    assert fields['dialogue']['items']['properties']['speaker']['enum'] == [*names, '旁白', 'Narrator']
    assert fields['narration']['items']['properties']['speaker']['enum'] == [*names, '旁白', 'Narrator']
    assert task.request_params['output_contract']['schema'] == schema


def test_empty_storyboard_candidates_do_not_allow_arbitrary_references():
    from schemas.text_task_contracts import output_contract, bind_storyboard_candidates
    original = output_contract('storyboard', blocking_maps=True)
    bound = bind_storyboard_candidates(original, [])
    fields = bound['schema']['properties']['shots']['items']['properties']
    assert fields['visible_asset_names']['maxItems'] == 0
    assert fields['blocking_map']['properties']['assets']['items']['properties']['asset_name'] == {'type': 'null'}
    assert fields['dialogue']['items']['properties']['speaker']['enum'] == ['旁白', 'Narrator']
    assert 'maxItems' not in original['schema']['properties']['shots']['items']['properties']['visible_asset_names']


@pytest.mark.asyncio
async def test_complete_episode_preserves_all_source_scene_numbers_in_one_call(project, monkeypatch):
    from copy import deepcopy
    novel, chapter, _ = project
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, source_chapters=[chapter.number])
    numbers = ['1-1', '1-2', '1-3']
    chapter.screenplay = '\n'.join(f'{number} 渡口 外 夜\n阿岚：等一等。' for number in numbers)
    await chapter.save()
    shots = [deepcopy(shot_payload()['shots'][0]) for _ in numbers]
    for number, shot in zip(numbers, shots):
        shot['source_scene_number'] = number
    requests = mock_model(monkeypatch, {'shots': shots})
    task = await scene_controller.generate(chapter.id)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    scenes = await Scene.filter(chapter=chapter).order_by('sequence')
    assert [scene.prompt_params['source_scene_number'] for scene in scenes] == numbers
    assert len(requests) == 1
