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
