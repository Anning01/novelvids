"""User requirements survive private chat -> production -> model boundaries."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from auth.deps import AuthContext
from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from schemas.agent_workflow import ProductionIntent
from services.creation_agent.intent_tools import submit_intent
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.skill_execution import SkillExecution, current_execution, prepare_workflow
from services.creation_agent.submissions import bind_submission
from test.test_services.test_creation_agent_sessions import session_fixture


async def chat_execution():
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={
        'message': '提取第一章资产，要把主角弄帅一些，特别一些，不要生图',
        'targets': [], 'write_scope': 'chapter',
    })
    parent = await agent_sessions.submit(conversation, request, AuthContext())
    parent.status = 2
    await parent.save(update_fields=['status'])
    parent.request_params['prompt_language'] = 'zh'
    assistant = await AgentMessage.get(task_id=parent.id, role='assistant')
    return request, SkillExecution(parent.request_params, assistant, AsyncMock())


@pytest.mark.asyncio
async def test_asset_intent_keeps_private_instruction_reference_and_replay():
    request, execution = await chat_execution()
    intent = ProductionIntent(operation='assets', target_id=request.chapter_id, request_id=uuid4())
    request = request.model_copy(update={'production_intents': [intent]})
    token = current_execution.set(execution)
    try:
        first = await submit_intent(intent, request=request, novel_id=execution.params['novel_id'])
        assert first == await submit_intent(intent, request=request, novel_id=execution.params['novel_id'])
    finally:
        current_execution.reset(token)
    child = await AiTask.get(id=first['task_id'])
    source = await AgentMessage.get(task_id=execution.params['task_id'], role='user')
    assert child.request_params['instruction_message_id'] == source.id
    assert request.message not in str(child.request_params)
    token = current_execution.set(SkillExecution({**child.request_params, 'task_id': str(child.id)}, None, AsyncMock()))
    try:
        grandchild = await prepare_workflow({'novel_id': execution.params['novel_id']})
        assert grandchild['instruction_message_id'] == source.id
    finally:
        current_execution.reset(token)
    assert 'instruction_message_id' not in await prepare_workflow({'novel_id': execution.params['novel_id']})


class CreativeOutput(BaseModel):
    text: str


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['zh', 'en'])
@pytest.mark.parametrize('skill', ['story', 'assets', 'authorization'])
async def test_model_receives_verbatim_creative_requirements_without_changing_authorization(language, skill):
    request, root = await chat_execution()
    token = current_execution.set(root)
    try:
        params = await prepare_workflow({'novel_id': root.params['novel_id'], 'prompt_language': language})
    finally:
        current_execution.reset(token)
    params['prompt_language'] = language
    child = await AiTask.create(task_type=5, status=2, request_params=params)
    from services.creation_agent.production import conversation_for_task
    message = await conversation_for_task(child)
    execution = SkillExecution({**params, 'task_id': str(child.id)}, message, AsyncMock())

    def respond(messages, info):
        content = next(part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart))
        if skill == 'authorization':
            assert isinstance(content, str)
            assert request.message not in content
        else:
            assert isinstance(content, list)
            assert 'Alex waits' in content[0]  # original facts remain present
            assert request.message in content[1]
            assert 'user' in content[1].lower() if language == 'en' else '用户' in content[1]
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {'text': 'ok', 'persons': [], 'scenes': [], 'items': []} if skill == 'assets' else {'text': 'ok'})])

    # This checks the shared model boundary; the extraction output contract is
    # independently exercised by test_skill_workflow's real asset schema tests.
    model = FunctionModel(respond)
    model.client = AsyncMock()
    from services.extraction.extractor import AssetExtractionResult

    class CreativeAssets(AssetExtractionResult):
        text: str

    output_type = CreativeAssets if skill == 'assets' else CreativeOutput
    with patch('services.creation_agent.handler.configured_model', return_value=model):
        result = await execution.generate(skill, {'chapter': 'Alex waits'}, output_type)
    assert result.text == 'ok'


@pytest.mark.asyncio
async def test_running_task_with_different_instruction_is_not_silently_reused():
    request, root = await chat_execution()
    source = await AgentMessage.get(task_id=root.params['task_id'], role='user')
    task = await AiTask.create(task_type=1, status=2, request_params={'instruction_message_id': source.id, 'novel_id': root.params['novel_id']})
    assert await bind_submission(task, task.request_params) == task
    with pytest.raises(HTTPException) as error:
        await bind_submission(task, {'novel_id': root.params['novel_id']})
    assert error.value.status_code == 409
    assert await AiTask.filter(task_type=1).count() == 1


@pytest.mark.asyncio
async def test_instruction_reference_cannot_cross_project_or_disappear_silently():
    from models.novel import Novel
    from services.creation_agent.skill_execution import user_instruction

    request, root = await chat_execution()
    source = await AgentMessage.get(task_id=root.params['task_id'], role='user')
    params = {**root.params, 'instruction_message_id': source.id}
    assert await user_instruction(params) == request.message
    other = await Novel.create(name='Other project')
    with pytest.raises(ValueError, match='原始创作要求'):
        await user_instruction({**params, 'novel_id': other.id})
    with pytest.raises(ValueError, match='原始创作要求'):
        await user_instruction({**params, 'team_id': 99999})
    with pytest.raises(ValueError, match='原始创作要求'):
        await user_instruction({**params, 'instruction_message_id': source.id + 99999})
    assert await user_instruction({'novel_id': other.id}) == ''
