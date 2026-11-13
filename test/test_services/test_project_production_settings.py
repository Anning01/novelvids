import pytest
from pydantic import ValidationError
from controllers.novel import novel_controller
from controllers.scene import scene_controller
from prompts.project_settings import audiovisual_guidance, default_audiovisual_guidance
from schemas.novel import NovelOut, NovelPatch
from test.test_services.test_skill_workflow import enabled_project


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_default_direction_is_complete_and_keeps_user_overrides(language):
    default = default_audiovisual_guidance(language)
    assert len(default) > 100
    assert audiovisual_guidance(None, language) == default
    assert audiovisual_guidance('  ', language) == default
    assert audiovisual_guidance('保留用户原有约定', language) == '保留用户原有约定'
    assert ('画外' in default) if language == 'zh' else ('offscreen' in default)


async def test_project_defaults_display_and_generation_share_maximum():
    novel, chapter, _ = await enabled_project()
    meta = await novel_controller.meta(novel.id)
    assert meta['shot_duration_max'] == 15
    assert meta['audiovisual_guidance'] == default_audiovisual_guidance()
    assert NovelOut.model_validate(novel).audiovisual_guidance == meta['audiovisual_guidance']
    task = await scene_controller.generate(chapter.id)
    assert task.request_params['shot_duration_range'] == [1, 15]


@pytest.mark.parametrize('value', [0, 31, None])
def test_invalid_maximum_rejected(value):
    with pytest.raises(ValidationError):
        NovelPatch(shot_duration_max=value)


async def test_agent_cannot_create_a_shot_over_the_project_limit():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from services.creation_agent.operations import CreationOperations
    from services.creation_objects import CreationObjects
    novel, chapter, _ = await enabled_project()
    service = SimpleNamespace(objects=CreationObjects(novel.id), scope=SimpleNamespace(chapter=AsyncMock(return_value=chapter)))
    with pytest.raises(ValueError, match='单分镜最长时长'):
        await CreationOperations(service).create_scene(SimpleNamespace(chapter_id=chapter.id, duration=16))
