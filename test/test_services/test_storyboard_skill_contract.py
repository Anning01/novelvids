"""Complete saved prompts and verbatim speech in the skill production path."""
import pytest
from prompts.skill_pack import SkillSnapshot, snapshot_skills
from prompts.storyboard import format_storyboard_prompt, normalized_storyboard_reference_fields, referenced_entities, normalize_storyboard_reference_text
from schemas.scene import SceneEntity
from test.test_services.test_prompt_language import _shot


def characters():
    return [SceneEntity(name='苏玄', aliases=[], description='十六岁少年', asset_type='人物'),
            SceneEntity(name='赵无垢', aliases=['师父'], description='六十四岁师父', asset_type='人物')]


def test_normalization_keeps_spoken_address_and_mentioned_names_verbatim():
    shot = _shot()
    shot.dialogue = ['0s-2s: 苏玄（哽咽）：「师父，赵无垢，你才六十四啊！」']
    shot.narration = ['2s-4s: 旁白（克制）：赵无垢是苏玄的师父。']
    updates = normalized_storyboard_reference_fields(shot, characters())
    assert updates['dialogue'] == ['0s-2s: @{苏玄}（哽咽）：「师父，赵无垢，你才六十四啊！」']
    assert 'narration' not in updates
    text = '0s-2s: 苏玄（哽咽）：「师父，赵无垢，你才六十四啊！」'
    assert normalize_storyboard_reference_text(text, characters()) == '0s-2s: @{苏玄}（哽咽）：「师父，赵无垢，你才六十四啊！」'


def test_renderer_preserves_literal_speech_and_does_not_cast_a_mentioned_person():
    shot = _shot()
    shot.description = '苏玄哭着喊师父'
    shot.spatial_relationships = '苏玄跪在坟前'
    shot.visual_prose = '@{苏玄}跪在坟前'
    shot.actions = ['0s-4s: @{苏玄}擦去眼泪。']
    shot.dialogue = ['0s-2s: 苏玄（哽咽）：「师父，赵无垢，你才六十四啊！」']
    shot.narration = ['2s-4s: 旁白（克制）：赵无垢是苏玄的师父。']
    assert [e.name for e in referenced_entities(shot, characters())] == ['苏玄']
    prompt = format_storyboard_prompt(shot, 'zh', entities=characters())
    assert '「师父，赵无垢，你才六十四啊！」' in prompt
    assert '赵无垢是苏玄的师父。' in prompt
    assert '@{赵无垢}' not in prompt


@pytest.mark.parametrize('language', ['zh','en'])
def test_skill_prompt_contract_rejects_summary_missing_voice_and_complete_sections(language):
    from services.storyboard.validation import validate_skill_storyboard_shot
    shot = _shot()
    shot.prompt = 'A short visual summary without the dialogue.'
    with pytest.raises(ValueError):
        validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(snapshot_skills()), language)


@pytest.mark.parametrize('language', ['zh','en'])
def test_complete_prompt_keeps_all_structured_content_and_timing(language):
    from services.storyboard.validation import validate_skill_storyboard_shot
    shot = _shot()
    shot.narration = ['0s-1s: Narrator (soft): The gate is closed.']
    shot.dialogue = ['2s-3s: Alex (quiet): Master, are you there?']
    shot.prompt = format_storyboard_prompt(shot, language)
    validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(snapshot_skills()), language)
    shot.prompt = shot.prompt.replace(shot.dialogue[0], '')
    with pytest.raises(ValueError):
        validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(snapshot_skills()), language)


def test_old_snapshot_keeps_the_historical_free_form_prompt_contract():
    from services.storyboard.validation import validate_skill_storyboard_shot
    raw = snapshot_skills(); raw['contents'].pop('storyboard_contract')
    shot = _shot(); shot.prompt = 'Saved historical prompt'
    validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(raw), 'zh')


@pytest.mark.parametrize('field,lines', [
    ('actions', ['0-5: The character walks.']),
    ('actions', ['The character walks.']),
    ('narration', ['2s-5s: Narrator: Words.']),
])
def test_contract_validates_timelines_even_without_an_s_suffix(field, lines):
    from services.storyboard.validation import validate_skill_storyboard_shot
    shot = _shot()
    setattr(shot, field, lines)
    shot.prompt = format_storyboard_prompt(shot, 'en')
    with pytest.raises(ValueError):
        validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(snapshot_skills()), 'en')


def test_contract_rejects_overlapping_voice_tracks():
    from services.storyboard.validation import validate_skill_storyboard_shot
    shot = _shot()
    shot.narration = ['0s-3s: Narrator: Words.']
    shot.dialogue = ['2s-4s: Alex: Master!']
    shot.prompt = format_storyboard_prompt(shot, 'en')
    with pytest.raises(ValueError):
        validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(snapshot_skills()), 'en')


@pytest.mark.parametrize('language', ['zh','en'])
def test_skill_instructions_preload_exact_localized_contract_labels(language):
    from prompts.skill_pack import instructions
    from prompts.labels import prompt_label
    rendered = instructions(SkillSnapshot.model_validate(snapshot_skills()), language, 'storyboard')
    assert prompt_label('【核心生成指令｜高优先级】', language) in rendered


def test_spoken_text_cannot_be_replaced_with_an_asset_marker():
    from services.storyboard.validation import validate_skill_storyboard_shot
    shot = _shot()
    shot.dialogue = ['0s-2s: 苏玄：@{赵无垢}！']
    shot.prompt = format_storyboard_prompt(shot, 'zh')
    with pytest.raises(ValueError):
        validate_skill_storyboard_shot(shot, SkillSnapshot.model_validate(snapshot_skills()), 'zh')


def test_voice_separator_handles_colons_in_emotion_and_literal_speech():
    from prompts.storyboard import split_storyboard_voice_track

    value = '1.5s-3s: Alex Chen（语气：克制）：他说：Master, wait!'
    prefix, speech = split_storyboard_voice_track(value)
    assert prefix == '1.5s-3s: Alex Chen（语气：克制）：'
    assert speech == '他说：Master, wait!'


def test_action_colons_do_not_hide_second_characters_reference():
    shot = _shot()
    shot.actions = ['0s-4s: 苏玄看向右侧：赵无垢抬起手。']
    assert normalized_storyboard_reference_fields(shot, characters())['actions'] == [
        '0s-4s: @{苏玄}看向右侧：@{赵无垢}抬起手。'
    ]


@pytest.mark.parametrize('field,value', [('actions', []), ('visual_prose', ''), ('sound_design', ' ')])
def test_new_storyboard_output_cannot_omit_required_action_or_prose(field, value):
    from services.storyboard.validation import validate_skill_storyboard_timing

    shot = _shot()
    setattr(shot, field, value)
    with pytest.raises(ValueError):
        validate_skill_storyboard_timing(shot)


@pytest.mark.asyncio
async def test_rejected_summary_never_replaces_the_chapters_existing_scenes(monkeypatch):
    from unittest.mock import AsyncMock
    from models.scene import Scene
    from controllers.scene import scene_controller
    from services.ai_task_executor import ai_task_executor
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from test.test_services.test_skill_workflow import enabled_project

    _, chapter, _ = await enabled_project()
    existing = await Scene.create(chapter=chapter, sequence=1, prompt='Original saved prompt', duration=4)
    def respond(messages, info):
        shot = _shot().model_dump(); shot['prompt'] = 'A summary that drops all voices.'
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'shots':[shot]})])
    model = FunctionModel(respond); model.client = AsyncMock()
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args:model)
    task = await scene_controller.generate(chapter.id, replace_existing=True)
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status == 4
    assert await Scene.filter(chapter=chapter).count() == 1
    await existing.refresh_from_db()
    assert existing.prompt == 'Original saved prompt'
    assert existing.deleted_at is None


def test_structure_is_serialized_once_using_frozen_strategy_and_literal_voice():
    from schemas.agent_workflow import StructuredSkillStoryboard
    from services.storyboard.validation import prepare_skill_storyboard
    from prompts.labels import prompt_label
    import json

    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    resource = json.loads(snapshot.read('strategies'))
    resource['narration']['restrictions'] = '冻结的策略限制'
    snapshot.contents['strategies'] = json.dumps(resource, ensure_ascii=False)
    shot = _shot().model_dump(exclude={'prompt','reference_only_types'})
    shot.update(visual_prose='@{苏玄}跪在坟前。', spatial_relationships='@{苏玄}位于坟前。',
                actions=['0s-4s: @{苏玄}擦去眼泪。'],
                narration=['0s-1s: 旁白：赵无垢长眠于此。'],
                dialogue=['1s-3s: @{苏玄}（哽咽）：师父！'])
    raw = StructuredSkillStoryboard.model_validate({'shots':[shot]})
    compiled = prepare_skill_storyboard(raw, snapshot, 'zh', characters(), 'narration').shots[0]
    assert compiled.prompt.startswith(prompt_label('【禁止项】','zh')+'\n冻结的策略限制')
    assert '【核心生成指令｜高优先级】' in compiled.prompt
    assert '1s-3s: @{苏玄}（哽咽）：师父！' in compiled.prompt
    assert '@{赵无垢}' not in compiled.prompt
    for name in ('actions','narration','dialogue'):
        assert all(line in compiled.prompt for line in getattr(compiled,name))
    assert compiled.reference_only_types == ['人物','场景','物品']
    assert raw.shots[0].prompt is None


@pytest.mark.asyncio
async def test_chat_structure_creation_and_visual_edit_use_the_same_complete_serializer():
    from unittest.mock import AsyncMock
    from copy import deepcopy
    from test.test_services.test_creation_agent_crud import crud
    from services.creation_agent.operations import CreationOperations
    from services.creation_agent.skill_execution import SkillExecution, current_execution
    from schemas.creation_agent import StoryboardVisualChanges

    service, scene, asset, _, _ = await crud()
    await scene.fetch_related('chapter__novel')
    scene.description = '雨后的师徒对话'
    await scene.save(update_fields=['description'])
    scene.chapter.novel.storyboard_strategy = 'narration'
    await scene.chapter.novel.save(update_fields=['storyboard_strategy'])
    await scene.assets.add(asset)
    shot = _shot().model_copy(update={
        'duration': f'{scene.duration:g}s',
        'visual_prose': f'@{{{asset.canonical_name}}} stands at the gate.',
        'actions': [f'0s-{scene.duration:g}s: @{{{asset.canonical_name}}} raises a hand.'],
        'narration': ['0s-1s: 旁白：雨停了。'],
        'dialogue': [f'1s-2s: @{{{asset.canonical_name}}}：师父！'],
    })
    execution = SkillExecution({'prompt_language':'zh','skill_snapshot':snapshot_skills()}, None, AsyncMock())
    token = current_execution.set(execution)
    try:
        operations = CreationOperations(service)
        await operations.scene_prompt(scene, structure=shot)
        await scene.refresh_from_db()
        assert '【核心生成指令｜高优先级】' in scene.prompt
        assert shot.dialogue[0] in scene.prompt
        assert scene.prompt_params['prompt_contract_version'] == 2
        previous = deepcopy(scene)
        await operations.scene_prompt(scene, visual=StoryboardVisualChanges(lighting_and_atmosphere='柔和暖光从左侧照入。'), previous=previous)
        await scene.refresh_from_db()
        assert '柔和暖光从左侧照入。' in scene.prompt
        assert shot.dialogue[0] in scene.prompt
        assert shot.narration[0] in scene.prompt
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_old_task_snapshot_still_requests_and_preserves_its_original_prompt_schema():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from schemas.agent_workflow import SkillShot, SkillStoryboard
    from services.creation_agent.skill_execution import current_execution
    from services.storyboard.generator import generate_storyboard

    raw = snapshot_skills()
    raw['contents'].pop('storyboard_contract')
    shot = SkillShot.model_validate({**_shot().model_dump(), 'prompt':'Historical prompt stays verbatim.'})
    result = SkillStoryboard(shots=[shot])
    execution = SimpleNamespace(snapshot=SkillSnapshot.model_validate(raw), params={'assistant_model_config_id':1},
                                generate=AsyncMock(return_value=result))
    token = current_execution.set(execution)
    try:
        saved, _ = await generate_storyboard(None, 'Original chapter', [], 'unused', prompt_language='zh')
        assert saved.shots[0].prompt == 'Historical prompt stays verbatim.'
        assert execution.generate.call_args.args[2] is SkillStoryboard
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_new_chat_visual_edit_cannot_silently_replace_historical_free_text():
    from copy import deepcopy
    from unittest.mock import AsyncMock
    from test.test_services.test_creation_agent_crud import crud
    from services.creation_agent.operations import CreationOperations
    from services.creation_agent.skill_execution import SkillExecution, current_execution
    from schemas.creation_agent import StoryboardVisualChanges

    service, scene, _, _, _ = await crud()
    await scene.fetch_related('chapter__novel')
    shot = _shot().model_copy(update={'duration':f'{scene.duration:g}s'})
    scene.description = shot.description
    scene.prompt = 'An independently edited historical prompt with extra facts.'
    scene.prompt_params = {**shot.model_dump(exclude={'prompt'}),'rendering_version':'agent-skills-v1'}
    await scene.save(update_fields=['description','prompt','prompt_params'])
    execution = SkillExecution({'prompt_language':'zh','skill_snapshot':snapshot_skills()}, None, AsyncMock())
    token = current_execution.set(execution)
    try:
        with pytest.raises(ValueError, match='历史手工提示词'):
            await CreationOperations(service).scene_prompt(scene,
                visual=StoryboardVisualChanges(lighting_and_atmosphere='暖光'),previous=deepcopy(scene))
        await scene.refresh_from_db()
        assert scene.prompt == 'An independently edited historical prompt with extra facts.'
    finally:
        current_execution.reset(token)


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_serialized_segments_keep_local_numbering_and_all_segment_content(language):
    import re
    from schemas.agent_workflow import StructuredSkillStoryboard
    from services.storyboard.validation import prepare_skill_storyboard
    from test.test_services.test_creation_agent_prompts import segmented_shot, heroine
    from prompts.labels import prompt_label

    shot = segmented_shot(sequence=17)
    raw = StructuredSkillStoryboard.model_validate({'shots':[shot.model_dump(exclude={'prompt','reference_only_types'})]})
    compiled = prepare_skill_storyboard(raw, SkillSnapshot.model_validate(snapshot_skills()), language, [heroine()], 'cinematic').shots[0]
    for segment in compiled.segments:
        assert segment.visual_prose in compiled.prompt
        assert all(action in compiled.prompt for action in segment.actions)
    assert '0s-2s' in compiled.prompt and '2s-4s' in compiled.prompt and '4s-6s' in compiled.prompt
    assert [int(n) for n in re.findall(re.escape(prompt_label('【镜头', language))+r'(\d+)\s*·', compiled.prompt)] == [1,2,3]
    assert compiled.sequence == 17
