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
        supports_json_output=True)
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
@pytest.mark.parametrize('task_kind', ['assets', 'storyboard'])
async def test_production_uses_one_strict_request_without_candidate_checks(project, monkeypatch, task_kind):
    novel, chapter, _ = project
    await Asset.create(novel=novel, canonical_name='阿岚', asset_type=1, base_traits='人工确认的设定', source_chapters=[1])
    requests = mock_model(monkeypatch, asset_payload() if task_kind == 'assets' else shot_payload())
    forbidden = AsyncMock(side_effect=AssertionError('legacy generation or review must not run'))
    monkeypatch.setattr(SkillExecution, 'generate', forbidden)
    monkeypatch.setattr('services.creation_agent.direct_plan.prepare_direct_plan', forbidden)
    monkeypatch.setattr('services.creation_agent.creative_checks.generate_checked', forbidden)
    # Resolve module-level aliases before temporarily replacing their source functions.
    import services.creation_agent.prompt_edits
    import services.creation_agent.operations
    for target in ('services.extraction.validation.AssetCandidateValidator.merge',
        'services.storyboard.candidates.StoryboardCandidateValidator.merge',
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
    assert len(requests) == 1 and requests[0]['response_format'] == {'type': 'json_object'}
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
