"""Chat proposals bind the same frozen export and quote as the button API."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from auth.deps import AuthContext
from controllers.chapter_export import chapter_exports
from models.ai_task import AiTask
from models.config import AiModelConfig
from models.creation_agent import AgentMessage
from models.chapter_export import ChapterExport
from schemas.agent_workflow import ProductionAuthorization
from schemas.creation_agent import AgentRunRequest
from services.creation_agent.authorization import pending_production, resolve_production_intents
from services.creation_agent.production import conversation_for_task
from services.creation_agent.skill_execution import SkillExecution, current_execution, prepare_workflow
from services.creation_agent.intent_tools import submit_intent
from services.video_enhancement.contract import ENHANCEMENT_PRESET
from services.video_enhancement.media import export_media, file_digest
from test.test_services.test_skill_workflow import enabled_project


@pytest.mark.asyncio
@pytest.mark.parametrize('message', ['请把这集增强为1080p', 'Do not enhance; explain the price only.'])
async def test_model_cannot_grant_enhancement_and_confirmed_intent_reuses_button_operation(message, tmp_path, monkeypatch):
    novel, chapter, _ = await enabled_project()
    config = await AiModelConfig.create(task_type=8, name='Processing', api_key='fake', is_active=True, **ENHANCEMENT_PRESET)
    path = tmp_path/'source.mp4'
    path.write_bytes(b'frozen source')
    @asynccontextmanager
    async def materialize(_ref):
        yield path
    monkeypatch.setattr(export_media, 'materialize', materialize)
    source = await ChapterExport.create(novel_id=novel.id, chapter_id=chapter.id,
        identity_key='a'*64, source_version='b'*64, source_media_ref='/media/exports/1/source.mp4',
        source_sha256=file_digest(path), source_probe={'duration':'5', 'width':864, 'height':496, 'fps':'24'})
    workflow = await prepare_workflow({'novel_id':novel.id, 'prompt_language':'en'})
    task = await AiTask.create(task_type=7, status=2, request_params=workflow)
    assistant = await conversation_for_task(task)
    user = await AgentMessage.get(task=task, role='user')
    request = AgentRunRequest(request_id=uuid4(), message=message, chapter_id=chapter.id, write_scope='chapter')
    user.run_input = request.model_dump(mode='json')
    await user.save()
    execution = SkillExecution({**workflow, 'task_id':str(task.id)}, assistant, AsyncMock())
    execution.generate = AsyncMock(return_value=ProductionAuthorization.model_validate({'intents':[
        {'operation':'enhance_export', 'target_id':source.id, 'source_quote':message}]}))
    token = current_execution.set(execution)
    try:
        resolved = await resolve_production_intents(request, novel.id, user)
        assert resolved.production_intents == []
        assert await AiTask.filter(task_type=8).count() == 0
        proposal = await pending_production(task.id)
        assert '1080p' in proposal['labels'][0]['target_label'] and '0.416667' in proposal['labels'][0]['target_label']
        from schemas.agent_workflow import ProductionIntent
        intent = ProductionIntent.model_validate(proposal['intents'][0])
        quote = await chapter_exports.quote(source, config.id, AuthContext())
        assert intent.enhancement.quote_version == quote['quote_version']
        if message.startswith('Do not'):
            with pytest.raises(ValueError):
                await submit_intent(intent, request=resolved, novel_id=novel.id)
        else:
            confirmed = request.model_copy(update={'production_intents':[intent]})
            receipt = await submit_intent(intent, request=confirmed, novel_id=novel.id)
            export, button_task = await chapter_exports.enhance(source.id, intent.enhancement, AuthContext())
            assert receipt['task_id'] == str(button_task.id)
            assert export.parent_export_id == source.id
            assert await AiTask.filter(task_type=8).count() == 1
    finally:
        current_execution.reset(token)
