from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.config import AiModelConfig
from schemas.agent_workflow import CompletePrompt
from schemas.ai_task import AiTaskOut
from schemas.scene import ScenePromptOptimization
from services.ai_task_executor import ai_task_executor
from services.creation_agent.skill_execution import SkillExecution
from services.storyboard.prompt_optimization import submit_prompt_optimization


@pytest.mark.asyncio
async def test_selected_models_and_retries_keep_the_original(configured_creation_agent, monkeypatch, tmp_path):
    novel = await Novel.create(name="救人")
    chapter = await Chapter.create(novel=novel, number=1, name="救人", content="原文")
    scene = await Scene.create(chapter=chapter, sequence=4, prompt="王许氏从门外喊话")
    generate = AsyncMock(return_value=CompletePrompt(prompt="模型专项稿"))
    monkeypatch.setattr(SkillExecution, "generate", generate)
    from config import settings
    monkeypatch.setattr(settings, "CREATION_AGENT_OPTIONAL_SKILLS_PATH", str(tmp_path))
    profiles = [("minimax_h3", "h3-prompt-writing", "minimax"), ("seedance_2_5", "sd25-pe", "volcengine_ark"),
                ("seedance_2_fast", "sd2-pe", "volcengine_ark"), ("wan_3", "wan3-pe", "dashscope")]
    for model_type, skill, protocol in profiles:
        (tmp_path / skill).mkdir()
        (tmp_path / skill / "SKILL.md").write_text(skill)
        config = await AiModelConfig.create(task_type=4, name=model_type, model=model_type,
            video_model_type=model_type, api_protocol=protocol, base_url="https://example.invalid", api_key="test", is_active=True)
        body = ScenePromptOptimization(model_config_id=config.id, generic_prompt=scene.prompt, duration=15,
            generation_mode="reference", aspect_ratio="16:9", submitted_media=[dict(type="image", label="王家牛棚")])
        task = await submit_prompt_optimization(scene.id, body, AuthContext())
        assert (await submit_prompt_optimization(scene.id, body, AuthContext())).id == task.id
        public = AiTaskOut.model_validate(task).model_dump()["request_params"]
        assert "video_optimizer" not in public and "prompt_inputs" not in public
        await ai_task_executor.run(task)
        await task.refresh_from_db()
        assert task.status == 3, task.error_message
        assert task.response_data["prompt"] == "模型专项稿"
        assert task.response_data["model_type"] == model_type
        assert skill in generate.await_args.kwargs["additional_instructions"]
        facts = generate.await_args.args[1]
        assert facts["submitted_media"][0]["label"] == "王家牛棚"
        assert facts["generic_prompt"] == scene.prompt
        assert (await submit_prompt_optimization(scene.id, body, AuthContext())).id == task.id
    await scene.refresh_from_db()
    assert scene.prompt == "王许氏从门外喊话"
    assert generate.await_count == len(profiles)
    monkeypatch.setattr("services.storyboard.prompt_optimization.snapshot_optimizer", lambda *_: {"mode": "missing"})
    with pytest.raises(HTTPException, match="优化技能"):
        await submit_prompt_optimization(scene.id, body, AuthContext())


@pytest.mark.parametrize('images', [[], [{'type': 'image', 'label': '苏玄'}]])
async def test_optimizer_requires_named_asset_bindings_with_or_without_images(images):
    from types import SimpleNamespace
    from services.creation_agent.skill_execution import current_execution
    from services.storyboard.prompt_optimization import PromptOptimizationHandler
    from prompts.video_optimizer import validate_asset_markers
    generic = '@{苏玄#十六岁}看着@{墓牌}，@{镜头时长:24s}'
    async def generate(skill, facts, output_type, **kwargs):
        assert 'without an actual submitted image' in kwargs['additional_instructions']
        with pytest.raises(ValueError, match='资产引用'):
            await kwargs['output_validator'](CompletePrompt(prompt='苏玄看着墓牌。'))
        result = CompletePrompt(prompt='[核心任务] @{苏玄#十六岁}看着@{墓牌}。')
        await kwargs['output_validator'](result)
        return result
    token = current_execution.set(SimpleNamespace(generate=generate))
    try:
        result = await PromptOptimizationHandler().execute({'scene_id': 1,
            'video_optimizer': {'mode': 'optimize', 'model_type': 'wan_3', 'skill': 'wan3-pe', 'files': {}},
            'prompt_inputs': {'generic_prompt': generic, 'submitted_media': images}})
    finally:
        current_execution.reset(token)
    validate_asset_markers(result['prompt'], generic)
    from services.video.content import process_subject_prompt
    rendered, _ = process_subject_prompt(result['prompt'], [
        {'name': '苏玄#十六岁', 'description': '十六岁灰蓝衣少年', 'images': []},
        {'name': '墓牌', 'description': '旧木墓牌', 'images': []}], 10)
    assert '十六岁灰蓝衣少年' in rendered and '旧木墓牌' in rendered


@pytest.mark.asyncio
async def test_chapter_optimization_survives_navigation_and_preserves_concurrent_edits(client, configured_creation_agent, monkeypatch, tmp_path):
    from config import settings
    from services.storyboard.prompt_batch import latest_batch, submit_batch
    from schemas.scene import ChapterPromptOptimization
    from models.ai_task import AiTask
    novel = await Novel.create(name='后台分镜')
    chapter = await Chapter.create(novel=novel, number=1, name='渡口', content='原文')
    scenes = [await Scene.create(chapter=chapter, sequence=i, prompt=f'通用稿{i}') for i in range(1, 5)]
    monkeypatch.setattr(settings, 'CREATION_AGENT_OPTIONAL_SKILLS_PATH', str(tmp_path))
    (tmp_path / 'sd25-pe').mkdir()
    (tmp_path / 'sd25-pe/SKILL.md').write_text('优化')
    model = await AiModelConfig.create(task_type=4, name='视频', model='video', video_model_type='seedance_2_5',
        api_protocol='volcengine_ark', base_url='https://example.invalid', api_key='test', is_active=True)
    import asyncio
    configured_creation_agent.concurrency = 2
    await configured_creation_agent.save(update_fields=['concurrency'])
    both_started, release = asyncio.Event(), asyncio.Event()
    active = 0

    async def render(*args, **kwargs):
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        try:
            await release.wait()
            return CompletePrompt(prompt='模型优化稿')
        finally:
            active -= 1

    generate = AsyncMock(side_effect=render)
    monkeypatch.setattr(SkillExecution, 'generate', generate)
    ctx = AuthContext()
    shots = [dict(scene_id=s.id, model_config_id=model.id, expected_prompt=s.prompt, generic_prompt=s.prompt,
        duration=6, generation_mode='reference', aspect_ratio='16:9', submitted_media=[]) for s in scenes]
    shots[1]['cached_prompt'] = '已有优化稿'
    body = ChapterPromptOptimization(shots=shots)
    from uuid import uuid4
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)
    endpoint = f'/api/scene/chapter/{chapter.id}/optimize-prompts'
    headers = {'X-Creation-Request-Id': str(uuid4())}
    admitted = (await client.post(endpoint, json=body.model_dump(), headers=headers)).json()
    assert admitted['code'] == 0, admitted
    task = await AiTask.get(id=admitted['data']['id'])
    assert generate.await_count == 0
    assert (await submit_batch(chapter.id, body, ctx)).id == task.id
    assert (await latest_batch(chapter.id, ctx)).id == task.id
    await Scene.filter(id=scenes[-1].id).update(prompt='用户新改的提示词')
    running = asyncio.create_task(ai_task_executor.run(task))
    try:
        await asyncio.wait_for(both_started.wait(), 5)
        assert (await latest_batch(chapter.id, ctx)).status == 2
    finally:
        release.set()
        await running
    assert generate.await_count == 2
    done = await latest_batch(chapter.id, ctx)
    assert done.status == 3, done.error_message
    assert sorted(done.response_data['saved_scene_ids']) == [s.id for s in scenes[:-1]], done.response_data
    assert done.response_data['failed_scene_ids'] == [scenes[-1].id]
    for s in scenes:
        await s.refresh_from_db()
    assert [s.prompt for s in scenes] == ['模型优化稿','已有优化稿','模型优化稿','用户新改的提示词']
    reopened = (await client.get(endpoint + '/latest')).json()['data']
    assert reopened['id'] == str(task.id) and reopened['response_data'] == done.response_data
    assert (await client.post(endpoint, json=body.model_dump(), headers=headers)).json()['data']['id'] == str(task.id)
    assert scenes[0].metadata['generic_video_prompt'] == '通用稿1'
    assert scenes[0].metadata['video_prompt_versions']['seedance_2_5']['prompt'] == '模型优化稿'
    assert await AiTask.filter(task_type=4).count() == 0
    assert 'prompt_batch_shots' not in AiTaskOut.model_validate(done).model_dump()['request_params']

    # A completed single-shot result stays reusable if applying the draft fails.
    from services.storyboard import prompt_batch
    shot = shots[-1] | {'expected_prompt': scenes[-1].prompt, 'generic_prompt': scenes[-1].prompt}
    retry_body = ChapterPromptOptimization(shots=[shot])
    with monkeypatch.context() as patch:
        patch.setattr(prompt_batch, 'apply_draft', AsyncMock(side_effect=ValueError('save failed')))
        attempt = await submit_batch(chapter.id, retry_body, ctx)
        await ai_task_executor.run(attempt)
        await attempt.refresh_from_db()
        assert attempt.response_data['failed_scene_ids'] == [scenes[-1].id]
    final = await submit_batch(chapter.id, retry_body, ctx)
    await ai_task_executor.run(final)
    await final.refresh_from_db()
    assert final.response_data['saved_scene_ids'] == [scenes[-1].id]
    assert generate.await_count == 3
