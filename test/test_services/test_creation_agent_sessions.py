import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from models.config import AiModelConfig
from models.creation_agent import AgentConversation, AgentMessage, AgentSettings
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from schemas.creation_agent import AgentRunRequest, AgentConfiguration
from services.creation_agent.sessions import agent_sessions
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def session_fixture():
    config = await AiModelConfig.create(task_type=AiTaskTypeEnum.creation_agent.value,
        name='test-agent', model='test-model', base_url='https://example.invalid/v1', api_key='fake-test-key', supports_tool_calls=True, is_active=True)
    await AgentSettings.update_or_create(id=1, defaults={'configuration': AgentConfiguration(enabled=True).model_dump()})
    novel = await Novel.create(name='会话测试')
    chapter = await Chapter.create(novel=novel, number=1, name='第一章', content='合成书稿')
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='空站台', duration=6)
    conversation = await agent_sessions.create(novel.id, AuthContext())
    request = AgentRunRequest(request_id=uuid4(), message='让光线更温暖', chapter_id=chapter.id,
        targets=[{'kind': 'scene', 'id': scene.id}])
    return conversation, request, config


@pytest.mark.asyncio
async def test_submit_keeps_private_text_out_of_general_task_and_is_idempotent():
    conversation, request, config = await session_fixture()
    first = await agent_sessions.submit(conversation, request, AuthContext())
    second = await agent_sessions.submit(conversation, request, AuthContext())
    assert first.id == second.id
    assert request.message not in str(first.request_params)
    assert 'fake-test-key' not in str(first.request_params)
    assert first.request_params['model_config_id'] == config.id
    assert await AgentMessage.filter(task_id=first.id).count() == 2


@pytest.mark.asyncio
async def test_concurrent_runs_in_one_conversation_are_serialized():
    conversation, request, _ = await session_fixture()
    results = await asyncio.gather(
        agent_sessions.submit(conversation, request, AuthContext()),
        agent_sessions.submit(conversation, request.model_copy(update={'request_id': uuid4()}), AuthContext()),
        return_exceptions=True,
    )
    assert sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results) == 1
    assert await AgentMessage.filter(conversation=conversation, role='user').count() == 1


@pytest.mark.asyncio
async def test_scope_and_changed_idempotency_payload_are_rejected():
    conversation, request, _ = await session_fixture()
    await agent_sessions.submit(conversation, request, AuthContext())
    with pytest.raises(HTTPException) as changed:
        await agent_sessions.submit(conversation, request.model_copy(update={'message': '不同内容'}), AuthContext())
    assert changed.value.status_code == 409
    other = await Novel.create(name='另一个项目')
    chapter = await Chapter.create(novel=other, number=1, name='第一章', content='另一个项目')
    other_scene = await Scene.create(chapter=chapter, sequence=1, prompt='越范围')
    other_conversation = await agent_sessions.create(conversation.novel_id, AuthContext())
    bad = request.model_copy(update={'request_id': uuid4(), 'targets': [request.targets[0].model_copy(update={'id': other_scene.id})]})
    with pytest.raises(HTTPException) as error:
        await agent_sessions.submit(other_conversation, bad, AuthContext())
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_terminated_run_does_not_keep_conversation_locked():
    conversation, request, _ = await session_fixture()
    first = await agent_sessions.submit(conversation, request, AuthContext())
    first.status = TaskStatusEnum.failed.value
    await first.save()
    second = await agent_sessions.submit(conversation, request.model_copy(update={'request_id': uuid4()}), AuthContext())
    assert second.id != first.id


@pytest.mark.asyncio
async def test_disabled_or_incapable_model_does_not_create_run():
    conversation, request, config = await session_fixture()
    config.supports_tool_calls = False
    await config.save()
    with pytest.raises(HTTPException) as error:
        await agent_sessions.submit(conversation, request, AuthContext())
    assert error.value.status_code == 422
    assert await AgentMessage.all().count() == 0
    await AgentSettings.filter(id=1).update(configuration=AgentConfiguration(enabled=False).model_dump())
    with pytest.raises(HTTPException) as error:
        await agent_sessions.submit(conversation, request, AuthContext())
    assert error.value.status_code == 403
