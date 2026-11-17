"""Current text workflow doubles for persistence tests; no external provider calls."""
from contextlib import contextmanager, asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from models.ai_task import AiTask
from models.config import AiModelConfig
from schemas.text_task_contracts import output_contract
from services.creation_agent.skill_execution import current_execution


@contextmanager
def analysis_execution(analysis):
    async def resolve(_params):
        return await AiModelConfig.filter(task_type=5).first(), None

    async def image_prompt(_skill, facts, output_type, **_options):
        from prompts.project_analysis import render_cover_prompt
        return output_type(prompt=render_cover_prompt(name=facts['name'], book_types=analysis.book_types,
            story_outline=facts['outline'], aspect_ratio=facts['aspect_ratio']))

    execution = SimpleNamespace(params={}, before_request=AsyncMock(), generate=AsyncMock(side_effect=image_prompt),
        generate_strict=AsyncMock(return_value=analysis.model_dump()))
    token = current_execution.set(execution)
    try:
        with patch('services.creation_agent.skill_execution.require_workflow_model', resolve):
            yield execution
    finally:
        current_execution.reset(token)


async def execute_analysis(params):
    from services.project_analysis.handler import ProjectAnalysisTaskHandler
    execution = current_execution.get()
    task = await AiTask.get(id=params['task_id']) if params.get('task_id') else await AiTask.create(task_type=5, status=2)
    execution.params = {**params, 'task_id': str(task.id), 'output_contract': output_contract('story')}
    return await ProjectAnalysisTaskHandler().execute(execution.params)


@asynccontextmanager
async def storyboard_execution(params):
    task = await AiTask.create(task_type=3, status=2, request_params=params)
    execution = SimpleNamespace(params={**params, 'task_id': str(task.id), 'output_contract': output_contract('storyboard')},
        before_request=AsyncMock())
    token = current_execution.set(execution)
    try:
        yield execution.params
    finally:
        current_execution.reset(token)


async def execute_storyboard(params):
    from models.chapter import Chapter
    from models.scene import Scene
    from services.creation_agent.plan_sources import fingerprint
    from services.creation_agent.object_state import object_version
    from services.storyboard.handler import StoryboardTaskHandler
    chapter = await Chapter.get(id=params['chapter_id'])
    versions = {str(scene.id): await object_version(scene) for scene in await Scene.filter(chapter=chapter)}
    params = {**params, 'novel_id': chapter.novel_id, 'replace_versions': versions,
        'scene_input_versions': versions,
        'chapter_input_version': fingerprint([chapter.name, chapter.production_text, chapter.episode_pacing])}
    async with storyboard_execution(params) as current:
        return await StoryboardTaskHandler().execute(current)
