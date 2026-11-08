"""Existing prompts are revised visibly before actual image/video dispatch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.asset import Asset
from models.creation_agent import AgentMessage, PromptChange
from models.scene import Scene
from prompts.skill_pack import SkillSnapshot
from schemas.agent_workflow import CompletePrompt, StructuredSkillStoryboard
from schemas.creation_plan import CreativeCheck
from services.creation_agent.media_execution import run_image_handler
from services.creation_agent.media_preparation import prepare_planned_media, validate_prepared_media
from services.creation_agent.object_state import object_version
from services.creation_agent.skill_execution import SkillExecution, current_execution
from services.reference.handler import AssetReferenceHandler
from test.test_services.test_asset_design_instructions import fixed_asset_prompt, synthetic_snapshot
from test.test_services.test_creation_plans import confirmed_fixture


async def media_fixture(operation='image'):
    _, _, plan, root, execution = await confirmed_fixture()
    if operation == 'image':
        target = await Asset.create(novel_id=plan.novel_id, asset_type=1, canonical_name='主角', base_traits='原有提示词', source_chapters=[1])
        extra = {'asset_id': target.id}
    else:
        target = await Scene.get(chapter_id=plan.steps[0].target_id)
        extra = {'video_request': {'scene_id': target.id}}
    step = plan.steps[0]
    step.operation, step.target_id = operation, target.id
    step.sources = []
    step.instructions = '保留已有设计，让光线更柔和。'
    plan.brief.requirements[0].instruction = '光线更柔和'
    plan.brief.requirements[0].acceptance = '使用柔和光线'
    plan.object_versions = {f"{'asset' if operation == 'image' else 'scene'}:{target.id}": await object_version(target)}
    plan.chapter_scenes = {}
    await AgentOperation.filter(task_id=execution.params['creation_plan_id'], key='creation:plan').update(result=plan.model_dump(mode='json'))
    params = {**root.request_params, **extra, 'creation_step_id': step.id, 'prompt_language': 'en',
        'skill_snapshot': synthetic_snapshot().model_dump()}
    child = await AiTask.create(task_type=2 if operation == 'image' else 4, status=2, request_params=params)
    params['task_id'] = str(child.id)
    child.request_params = params
    await child.save(update_fields=['request_params'])
    message = await AgentMessage.create(conversation_id=execution.message.conversation_id, task=child,
        role='assistant', request_id=uuid4(), request_hash='media-test')
    return target, SkillExecution(params, message, AsyncMock())


def passed_check():
    return CreativeCheck(plan_followed=True, findings=[{
        'requirement_id': 'opening', 'passed': True, 'location': 'prompt', 'detail': '已使用柔和光线'}])


@pytest.mark.asyncio
async def test_existing_image_prompt_reaches_provider_and_is_reversible():
    target, execution = await media_fixture()
    prompt = fixed_asset_prompt('en', snapshot=execution.snapshot).replace('Realistic drama', 'Realistic drama, soft window light')
    async def generate(skill, facts, output_type, **kwargs):
        if skill == 'creative_check':
            return passed_check()
        assert facts['current_prompt'] == '原有提示词'
        return CompletePrompt(prompt=prompt)
    token = current_execution.set(execution)
    try:
        with patch.object(execution, '_generate', side_effect=generate), \
             patch('services.reference.generator.generate_images', AsyncMock(return_value=[SimpleNamespace(url='https://example.invalid/image.png')])) as provider, \
             patch('services.reference.handler._persist_generated_image', AsyncMock(return_value='/media/test.png')):
            params = {**execution.params, 'base_url': 'https://example.invalid', 'api_key': 'test-key', 'model': 'test'}
            result = await run_image_handler(AssetReferenceHandler(), params)
            replay = await run_image_handler(AssetReferenceHandler(), params)
        assert result == replay
        assert provider.await_count == 1
        await target.refresh_from_db()
        assert provider.call_args.kwargs['prompt'] == target.base_traits == prompt
        change = await PromptChange.get(task_id=execution.params['task_id'])
        assert change.changes[0]['before']['base_traits'] == '原有提示词'
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_rejected_image_candidate_never_changes_original_or_calls_provider():
    target, execution = await media_fixture()
    prompt = fixed_asset_prompt('en', snapshot=execution.snapshot)
    async def generate(skill, facts, output_type, **kwargs):
        if skill == 'creative_check':
            return CreativeCheck(plan_followed=False, findings=[{'requirement_id': 'opening', 'passed': False,
                'location': '未找到', 'detail': '缺少柔光'}], issues=['缺少柔光'])
        return CompletePrompt(prompt=prompt)
    token = current_execution.set(execution)
    try:
        with patch.object(execution, '_generate', side_effect=generate), \
             patch('services.reference.generator.generate_images', AsyncMock()) as provider, pytest.raises(ValueError, match='未覆盖'):
            await run_image_handler(AssetReferenceHandler(), execution.params)
        provider.assert_not_called()
        await target.refresh_from_db()
        assert target.base_traits == '原有提示词'
        assert not await AgentOperation.filter(task_id=execution.params['task_id'], key='media:image').exists()
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_concurrent_edit_between_candidate_and_save_is_preserved():
    target, execution = await media_fixture()
    prompt = fixed_asset_prompt('en', snapshot=execution.snapshot)
    async def generate(skill, facts, output_type, **kwargs):
        if skill == 'creative_check':
            await Asset.filter(id=target.id).update(base_traits='用户刚刚修改')
            return passed_check()
        return CompletePrompt(prompt=prompt)
    with patch.object(execution, '_generate', side_effect=generate), pytest.raises(ValueError, match='新修改'):
        await prepare_planned_media(execution, kind='asset', target=target)
    await target.refresh_from_db()
    assert target.base_traits == '用户刚刚修改'


@pytest.mark.asyncio
async def test_video_rewrites_existing_prompt_and_rechecks_before_submission():
    from test.test_services.test_storyboard_prompts import _shot
    target, execution = await media_fixture('video')
    shot = _shot(1)
    shot.duration = f'{target.duration:g}s'
    shot.visual_prose = '空站台，柔和的灯光照亮长椅。'
    shot.actions = [f'0s-{target.duration:g}s: 镜头缓缓接近空长椅。']
    async def generate(skill, facts, output_type, **kwargs):
        if skill == 'creative_check':
            return passed_check()
        assert facts['current_prompt'] == '空站台'
        return StructuredSkillStoryboard.model_validate({'shots': [shot.model_dump(exclude={'prompt'})]})
    token = current_execution.set(execution)
    try:
        with patch.object(execution, '_generate', side_effect=generate):
            await prepare_planned_media(execution, kind='scene', target=target)
        await target.refresh_from_db()
        assert '柔和的灯光' in target.prompt
        assert target.prompt_params['visual_prose'] == shot.visual_prose
        await validate_prepared_media(execution, target)
        await Scene.filter(id=target.id).update(prompt='用户更新的视频提示词')
        with pytest.raises(ValueError, match='不同'):
            await validate_prepared_media(execution, target)
    finally:
        current_execution.reset(token)


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_plan_prompts_render_language_and_preserve_mandatory_protocol(language):
    from prompts.creation_plan import step_requirements, correction_instructions
    from prompts.skill_pack import instructions, snapshot_skills
    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    for name in ('planning_request', 'source_reading', 'creation_planning', 'creative_check'):
        assert f'language={language}' in instructions(snapshot, language, name)
    assert 'step_context' in step_requirements(language)
    assert correction_instructions(language)


@pytest.mark.asyncio
async def test_historical_token_cap_does_not_stop_a_confirmed_run():
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    target, execution = await media_fixture()
    execution.params['agent_configuration']['total_tokens_limit'] = 1000
    await AgentMessage.filter(task_id=execution.params['creation_run_id'], role='assistant').update(usage={'input_tokens': 1000})
    model = FunctionModel(lambda messages, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'prompt': '继续执行'})]))
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await execution._generate('video', {}, CompletePrompt)
    receipt = await AgentOperation.get(task_id=execution.params['task_id'], key='model:video:CompletePrompt:')
    assert receipt.state == 'completed' and result.prompt == '继续执行'


@pytest.mark.asyncio
async def test_prior_planning_usage_does_not_consume_the_confirmed_round_budget():
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    _, execution = await media_fixture()
    execution.params['agent_configuration']['total_tokens_limit'] = 1000
    await AgentMessage.filter(task_id=execution.params['creation_plan_id'], role='assistant').update(usage={'input_tokens': 2000})
    model = FunctionModel(lambda messages, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'prompt': '完整候选'})]))
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await execution._generate('video', {}, CompletePrompt)
    assert result.prompt == '完整候选'


@pytest.mark.asyncio
@pytest.mark.parametrize('strategy', ['cinematic', 'narration'])
async def test_storyboard_resources_are_supplied_without_extra_skill_calls(strategy):
    import json
    from models.novel import Novel
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel
    _, execution = await media_fixture()
    await Novel.filter(id=execution.params['novel_id']).update(custom_style_prompt='已配置的画面风格', storyboard_strategy=strategy)
    def respond(messages, info):
        assert not info.function_tools
        content = next(part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart))
        project = json.loads(content[0])['untrusted_task_facts']['project']
        assert project['video_style'] == '已配置的画面风格'
        assert project['storyboard_rules'] == json.loads(execution.snapshot.read('strategies'))[strategy]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'prompt': '完整候选'})])
    model = FunctionModel(respond); model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        await execution._generate('video', {}, CompletePrompt)


@pytest.mark.asyncio
async def test_unknown_storyboard_reference_is_repaired_before_the_result_is_accepted():
    from pydantic_ai.messages import ModelResponse, ToolCallPart, RetryPromptPart
    from pydantic_ai.models.function import FunctionModel
    from schemas.scene import SceneEntity
    from test.test_services.test_storyboard_prompts import _shot
    _, execution = await media_fixture()
    calls = 0
    def respond(messages, info):
        nonlocal calls
        calls += 1
        shot = _shot(1)
        if calls == 1:
            shot.visual_prose = '@{不存在的设定}出现。'
        else:
            assert any(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'shots': [shot.model_dump(exclude={'prompt'})]})])
    model = FunctionModel(respond); model.client = AsyncMock()
    entity = SceneEntity(name='郊区小楼', aliases=[], description='旧楼', asset_type='场景')
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await execution._generate('storyboard', {'entities': [entity.model_dump()], 'strategy': 'cinematic'}, StructuredSkillStoryboard)
    assert calls == 2 and '不存在' not in result.shots[0].visual_prose


@pytest.mark.asyncio
@pytest.mark.parametrize('skill', ['assets', 'storyboard', 'image', 'video'])
async def test_actual_model_boundary_contains_scoped_plan_and_verbatim_sources(skill):
    import json
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel
    from services.extraction.extractor import AssetExtractionResult
    from test.test_services.test_storyboard_prompts import _shot
    _, _, plan, _, execution = await confirmed_fixture()
    execution.params['creation_step_id'] = 'chapter1'
    output_type = AssetExtractionResult if skill == 'assets' else StructuredSkillStoryboard if skill == 'storyboard' else CompletePrompt
    response = {'persons': [], 'scenes': [], 'items': []} if skill == 'assets' else {
        'shots': [_shot(1).model_dump(exclude={'prompt'})]} if skill == 'storyboard' else {'prompt': 'The gate collapses, then cut back to the letter.'}
    captured = []
    def respond(messages, info):
        content = next(part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart))
        facts = json.loads(content[0])['untrusted_task_facts']
        context = facts['step_context']
        assert context['sources'][0]['text'] == plan.excerpts[0].text
        assert context['step']['instructions'] == plan.steps[0].instructions
        assert context['requirements'][0]['id'] == 'opening'
        assert 'step_context' in content[1]
        captured.append(facts)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, response)])
    model = FunctionModel(respond)
    model.client = AsyncMock()
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        await execution._generate(skill, {'chapter': '当前章正文'}, output_type)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_image_finishing_after_a_user_edit_does_not_replace_current_media():
    target, execution = await media_fixture()
    prompt = fixed_asset_prompt('en', snapshot=execution.snapshot)
    async def generate(skill, facts, output_type, **kwargs):
        return passed_check() if skill == 'creative_check' else CompletePrompt(prompt=prompt)
    async def provider(**kwargs):
        await Asset.filter(id=target.id).update(base_traits='用户修改后的提示词', main_image='/media/user-selected.png')
        return [SimpleNamespace(url='https://example.invalid/image.png')]
    token = current_execution.set(execution)
    try:
        with patch.object(execution, '_generate', side_effect=generate), \
             patch('services.reference.generator.generate_images', side_effect=provider), \
             patch('services.reference.handler._persist_generated_image', AsyncMock(return_value='/media/new-candidate.png')):
            result = await run_image_handler(AssetReferenceHandler(), {**execution.params,
                'base_url': 'https://example.invalid', 'api_key': 'test-key', 'model': 'test'})
        await target.refresh_from_db()
        assert target.main_image == '/media/user-selected.png'
        assert target.base_traits == '用户修改后的提示词'
        assert result['images'] == ['/media/new-candidate.png'] and result['not_applied_reason']
    finally:
        current_execution.reset(token)


@pytest.mark.asyncio
async def test_direct_media_button_regenerates_without_rewriting_saved_prompt():
    from services.creation_agent.direct_plan import prepare_direct_plan
    from services.creation_agent.plan_execution import existing_result
    from services.creation_agent.plans import load_plan
    target, execution = await media_fixture()
    for key in ('creation_plan_id', 'creation_step_id', 'creation_run_id', 'instruction_message_id'):
        execution.params.pop(key, None)
    await Asset.filter(id=target.id).update(main_image='/media/existing.png')
    await target.refresh_from_db()
    task = await AiTask.get(id=execution.params['task_id'])
    await AgentMessage.create(conversation_id=execution.message.conversation_id, task=task, role='user',
        request_id=uuid4(), request_hash='button', content='生成图片', run_input={})
    await prepare_direct_plan(task, execution)
    plan = await load_plan(task.id)
    assert plan.steps[0].mode == 'regenerate'
    assert await existing_result(plan.steps[0], target.id) is None
    with patch.object(execution, '_generate', AsyncMock()) as model:
        await prepare_planned_media(execution, kind='asset', target=target)
    model.assert_not_called()
    await target.refresh_from_db()
    assert target.base_traits == '原有提示词'
