import asyncio
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic_ai.messages import RetryPromptPart, SystemPromptPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from auth.deps import AuthContext
from config import settings
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.creation_agent import AgentConversation, AgentMessage
from models.novel import Novel
from models.scene import Scene
from prompts.deep_agent import summary_instructions
from services.ai_task_executor import AiTaskExecutor
from services.creation_agent.deep_runtime import create_runtime, public_events
from services.creation_agent.production import conversation_for_task
from services.creation_agent.project_facts import load_project_facts, CATALOG_PATH
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.skill_execution import prepare_workflow
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_default_session_is_atomic_and_buttons_reuse_it_without_replacing_active_chat():
    conversation, request, _ = await session_fixture()
    active = await agent_sessions.submit(conversation, request, AuthContext())
    resolved = await asyncio.gather(*[agent_sessions.default(conversation.novel_id, AuthContext()) for _ in range(5)])
    assert {row.id for row in resolved} == {conversation.id}
    for number in (2, 10):
        chapter = await Chapter.create(novel_id=conversation.novel_id, number=number, name=str(number), content='合成')
        params = await prepare_workflow({'novel_id': conversation.novel_id, 'chapter_id': chapter.id})
        task = await AiTask.create(task_type=1, status=2, request_params=params)
        message = await conversation_for_task(task)
        assert message.conversation_id == conversation.id
    await conversation.refresh_from_db()
    assert conversation.active_task_id == active.id
    assert await AgentConversation.filter(novel_id=conversation.novel_id).count() == 1
    explicit = await agent_sessions.create(conversation.novel_id, AuthContext())
    assert explicit.id != conversation.id
    assert (await agent_sessions.default(conversation.novel_id, AuthContext())).id == explicit.id
    assert (await agent_sessions.default(conversation.novel_id, AuthContext(), conversation.id)).id == conversation.id


@pytest.mark.asyncio
async def test_button_cannot_attach_to_another_project_or_deleted_conversation():
    conversation, _, _ = await session_fixture()
    other = await Novel.create(name='其他作品')
    with pytest.raises(HTTPException) as mismatch:
        await agent_sessions.default(other.id, AuthContext(), conversation.id)
    assert mismatch.value.status_code == 404
    await agent_sessions.set_deleted(conversation.id, AuthContext(), deleted=True)
    with pytest.raises(HTTPException):
        await agent_sessions.default(conversation.novel_id, AuthContext(), conversation.id)
    assert (await agent_sessions.default(conversation.novel_id, AuthContext())).id != conversation.id


async def identity_fixture():
    conversation, request, _ = await session_fixture(runtime='deepagents')
    novel = await Novel.get(id=conversation.novel_id)
    from test.project_identity_fixture import seed_project_identities
    hero, variants, tenth, scene = await seed_project_identities(novel)
    return conversation, request, novel, hero, variants, tenth, scene


@pytest.mark.asyncio
async def test_catalog_is_fresh_project_scoped_and_keeps_all_three_identity_ids():
    conversation, _, novel, hero, variants, tenth, _ = await identity_fixture()
    other = await Novel.create(name='其他私有作品')
    await Asset.create(novel=other, canonical_name='不应出现', asset_type=1)
    summary, manifest = await load_project_facts(novel_id=novel.id, chapter_id=tenth.id,
        page_size=32, character_budget=4000, authorize=AsyncMock())
    assert summary['saved_assets'] == 1 and summary['saved_variants'] == 3
    assert summary['asset_groups'][0]['id'] == hero.id
    assert [item['id'] for item in summary['asset_groups'][0]['variants']] == [variant.id for variant in variants]
    assert summary['world_and_style']['custom_style_prompt'] == novel.custom_style_prompt
    assert '不应出现' not in manifest
    assert summary['catalog_path'] == CATALOG_PATH
    assert len(manifest.splitlines()) == 5
    limited, complete = await load_project_facts(novel_id=novel.id, chapter_id=tenth.id,
        page_size=32, character_budget=10, authorize=AsyncMock())
    assert limited['preview_has_more'] and not limited['asset_groups']
    assert all(variant.name in complete for variant in variants)
    await AssetVariant.filter(id=variants[0].id).update(description='数据库当前最新确认描述')
    fresh, _ = await load_project_facts(novel_id=novel.id, chapter_id=tenth.id,
        page_size=32, character_budget=4000, authorize=AsyncMock())
    assert fresh['asset_groups'][0]['variants'][0]['description'] == '数据库当前最新确认描述'
    assert '真实 ID' in summary_instructions('zh')


@pytest.mark.asyncio
async def test_tenth_chapter_after_sdk_compaction_restart_and_new_chat_reuses_old_variant(monkeypatch, tmp_path):
    from services.creation_agent.handler import CreationAgentTaskHandler
    from services.creation_agent.deep_execution import skill_files
    from prompts.skill_pack import SkillSnapshot, snapshot_skills
    from test.probes.deep_runtime import ScriptedModel
    from services.creation_agent.event_log import agent_event_log

    conversation, request, novel, hero, variants, tenth, scene = await identity_fixture()
    from langchain_core.messages import AIMessage

    class CompactionModel(ScriptedModel):
        def response(self, messages, tools):
            return AIMessage(content='历史已整理；身份以当前登记目录为准。' if not tools else '已读本轮资料。')

    path = str(tmp_path / 'identities.db')
    monkeypatch.setattr(settings, 'CREATION_AGENT_CHECKPOINT_PATH', path)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_runtime(model=CompactionModel(), tools=[], instructions='旧对话不作为当前目录。', checkpointer=saver,
            summarization={'trigger': ('messages', 6), 'keep': ('messages', 2), 'summary_prompt': summary_instructions('zh')})
        for number in range(5):
            async for _ in public_events(graph, {'messages': [HumanMessage(f'长会话第{number}轮。')],
                    'files': skill_files(SkillSnapshot.model_validate(snapshot_skills()))}, thread_id=f'conversation:{conversation.id}', run_id=str(number)):
                pass
        state = await graph.aget_state({'configurable': {'thread_id': f'conversation:{conversation.id}'}})
        assert state.values.get('_summarization_event')

    count = 0
    tool_feedback = []
    async def respond(messages, info):
        nonlocal count
        if not info.function_tools:
            yield '已整理历史，身份以当前已登记目录为准。'
            return
        count += 1
        system = '\n'.join(part.content for message in messages for part in message.parts if isinstance(part, SystemPromptPart))
        assert all(variant.name in system for variant in variants)
        assert str(hero.id) in system and novel.custom_style_prompt in system
        if count == 1:
            yield {0: DeltaToolCall(name='read_creation_objects', tool_call_id='read-before-binding', json_args=json.dumps({
                'targets': [{'kind': 'scene', 'id': scene.id}, {'kind': 'asset', 'id': hero.id}, {'kind': 'variant', 'id': variants[0].id}],
                'chapter_id': tenth.id}))}
        elif count == 2:
            yield {0: DeltaToolCall(name='link_scene_references', tool_call_id='bind-old-identity', json_args=json.dumps({
                'scene_id': scene.id, 'asset_ids': [hero.id], 'variant_ids': [variants[0].id]}))}
        else:
            feedback = [part for message in messages for part in message.parts
                        if isinstance(part, (ToolReturnPart, RetryPromptPart)) and part.tool_name == 'link_scene_references']
            if count == 3 and feedback:
                tool_feedback.append(str(feedback[-1].content))
            yield '第十章回忆已引用原渡口学徒身份，没有新建卡片。'

    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args, **kwargs: FunctionModel(stream_function=respond))
    scoped = request.model_copy(update={'request_id': uuid4(), 'message': '第十章回忆第二章，请引用已登记的渡口学徒身份，不新建卡。',
        'write_scope': 'chapter', 'chapter_id': tenth.id, 'targets': []})
    task = await agent_sessions.submit(conversation, scoped, AuthContext())
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
    await scene.refresh_from_db()
    assert scene.metadata['asset_variant_ids'] == {str(hero.id): variants[0].id}, tool_feedback
    assert '渡口学徒' in scene.prompt
    assert '灯塔守望者' not in scene.prompt
    assert await Asset.filter(novel=novel).count() == 1
    assert await AssetVariant.filter(asset=hero).count() == 3
    fresh = await agent_sessions.create(novel.id, AuthContext())
    count = 2  # New chat must receive the current catalog even with no history.
    next_task = await agent_sessions.submit(fresh, scoped.model_copy(update={'request_id': uuid4(), 'message': '只核对已登记三种身份，不修改。', 'write_scope': 'read_only'}), AuthContext())
    await executor.run(next_task)
    await next_task.refresh_from_db()
    assert next_task.status == 3, next_task.error_message
    assert await Asset.filter(novel=novel).count() == 1


@pytest.mark.asyncio
async def test_stopped_old_task_is_not_an_implicit_pending_request(monkeypatch, tmp_path):
    from pydantic_ai.messages import SystemPromptPart
    from services.creation_agent.handler import CreationAgentTaskHandler
    conversation, request, _ = await session_fixture(runtime='deepagents')
    old = await agent_sessions.submit(conversation, request.model_copy(update={'message': '写一篇长评论'}), AuthContext())
    await AiTask.filter(id=old.id).update(status=5)
    await AgentMessage.filter(task=old, role='assistant').update(content='未写完的旧评论')
    for _ in range(15):
        internal = await AiTask.create(task_type=7, status=3, request_params={'novel_id': conversation.novel_id})
        await AgentMessage.create(conversation=conversation, task=internal, request_id=internal.id, request_hash='internal',
            role='assistant', run_input={'internal_production_step': True})
    monkeypatch.setattr(settings, 'CREATION_AGENT_CHECKPOINT_PATH', str(tmp_path / 'lifecycle.db'))
    async def respond(messages, info):
        system = '\n'.join(part.content for message in messages for part in message.parts if isinstance(part, SystemPromptPart))
        assert 'cancelled' in system and '只回查三个登记身份' in system
        assert '不自动补写' in system
        yield '本轮只回查登记事实，不继续旧评论。'
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args, **kwargs: FunctionModel(stream_function=respond))
    task = await agent_sessions.submit(conversation, request.model_copy(update={'request_id': uuid4(), 'message': '只回查三个登记身份'}), AuthContext())
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == 3, task.error_message
