from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
from pydantic_ai.models.function import FunctionModel

from models.ai_task import AiTask
from models.creation_agent import AgentMessage, CreationConstraint
from schemas.creation_agent import AgentConfiguration
from services.creation_agent.history import prepare_history
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import TaskStatusEnum


@pytest.mark.asyncio
async def test_incremental_summary_preserves_recent_tool_history_and_constraint_records():
    import json
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    conversation, _, _ = await session_fixture()
    for number in range(4):
        task = await AiTask.create(task_type=7, status=TaskStatusEnum.completed.value)
        request_id = uuid4()
        user = await AgentMessage.create(conversation=conversation, task=task, role='user', request_id=request_id,
            request_hash='test', content=f'第{number}轮要求')
        await AgentMessage.create(conversation=conversation, task=task, role='assistant', request_id=request_id,
            request_hash='test', content=f'第{number}轮已完成', native_messages=json.loads(ModelMessagesTypeAdapter.dump_json([
                ModelRequest(parts=[UserPromptPart(f'第{number}轮要求')]), ModelResponse(parts=[TextPart(f'第{number}轮已完成')])
            ])))
        if number == 0:
            await CreationConstraint.create(novel_id=conversation.novel_id, source_message=user, fingerprint='test',
                content='女主穿灰色风衣', source_quote='灰色风衣', scope={'kind': 'project'})
    current_task = await AiTask.create(task_type=7)
    current = await AgentMessage.create(conversation=conversation, task=current_task, role='assistant', request_id=uuid4(), request_hash='current')
    calls = []
    def model(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[TextPart('已调整前两轮光线，保留人物设定。')])
    limits = AgentConfiguration(history_runs=2)
    history = await prepare_history(conversation, current, limits, FunctionModel(model))
    assert len(calls) == 1
    assert len(history) == 6
    assert history[2].parts[0].content == '第2轮要求'
    assert conversation.summary_until_id > 0
    again = await prepare_history(conversation, current, limits, FunctionModel(model))
    assert len(calls) == 1 and len(again) == 6
    assert await CreationConstraint.filter(novel_id=conversation.novel_id).count() == 1


@pytest.mark.asyncio
async def test_failed_summary_uses_extract_checkpoint_without_deleting_history():
    conversation, _, _ = await session_fixture()
    for number in range(3):
        task = await AiTask.create(task_type=7, status=TaskStatusEnum.completed.value)
        await AgentMessage.create(conversation=conversation, task=task, role='assistant', request_id=uuid4(), request_hash='test', content=f'回复{number}')
    task = await AiTask.create(task_type=7)
    current = await AgentMessage.create(conversation=conversation, task=task, role='assistant', request_id=uuid4(), request_hash='current')
    def failing(messages, info):
        raise RuntimeError('summary unavailable')
    history = await prepare_history(conversation, current, AgentConfiguration(history_runs=1), FunctionModel(failing))
    assert history
    await conversation.refresh_from_db()
    assert conversation.summary_until_id > 0 and '回复' in conversation.summary
    from models.creation_agent import AgentContextCheckpoint
    assert await AgentContextCheckpoint.filter(conversation=conversation, kind='extractive_summary').count() == 1
    assert await AgentMessage.filter(conversation=conversation).count() == 4


@pytest.mark.asyncio
async def test_large_history_is_summarized_before_the_turn_count_limit():
    import json
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    conversation, _, _ = await session_fixture()
    previous = await AiTask.create(task_type=7, status=TaskStatusEnum.completed.value)
    await AgentMessage.create(conversation=conversation, task=previous, role='assistant', request_id=uuid4(),
        request_hash='long', content='已修改目标12的画面', native_messages=json.loads(ModelMessagesTypeAdapter.dump_json([
            ModelResponse(parts=[TextPart('历史完整提示词' * 1500)])])))
    current_task = await AiTask.create(task_type=7)
    current = await AgentMessage.create(conversation=conversation, task=current_task, role='assistant', request_id=uuid4(), request_hash='now')
    calls = []
    def summarize(messages, info):
        calls.append(messages)
        return ModelResponse(parts=[TextPart('上一轮调整了目标12的画面。')])
    history = await prepare_history(conversation, current, AgentConfiguration(history_runs=6, max_context_characters=2000), FunctionModel(summarize))
    assert len(calls) == 1
    assert history and '历史完整提示词' not in str(history)
    assert '目标12' in conversation.summary
