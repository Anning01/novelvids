from uuid import uuid4
import asyncio

import pytest
from pydantic import ValidationError

from auth.deps import AuthContext
from models.chapter import Chapter
from models.creation_agent import AgentMessage, CreationConstraint
from models.scene import Scene
from schemas.creation_agent import AgentRunRequest, CreationConstraintProposal, CreationConstraintScope
from services.creation_agent.memory import creation_memory
from services.creation_agent.sessions import agent_sessions
from test.test_services.test_creation_agent_sessions import session_fixture


async def memory_fixture():
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'message': '记住，这场戏都用暖光。第三章人物受伤，之后直到第四章都保留左手绷带。'})
    task = await agent_sessions.submit(conversation, request, AuthContext())
    source = await AgentMessage.get(task=task, role='user')
    chapters = [await Chapter.create(novel_id=conversation.novel_id, number=n, name=f'第{n}章', content='合成书稿') for n in (2, 3, 4)]
    scenes = [await Scene.create(chapter=chapter, sequence=1, prompt='合成镜头', duration=4) for chapter in chapters]
    return conversation, request, source, chapters, scenes


@pytest.mark.asyncio
async def test_new_scene_generation_reuses_project_rules_without_old_scene_or_other_chapter_rules():
    from models.asset import Asset
    conversation, request, source, chapters, _ = await memory_fixture()
    person = await Asset.create(novel_id=conversation.novel_id, canonical_name='林夏', asset_type=1)
    scopes = [
        ('人物外貌', {'kind': 'project', 'asset_id': person.id}),
        ('第三章绷带', {'kind': 'range', 'start_chapter': 3, 'end_chapter': 4}),
        ('第二章晨光', {'kind': 'chapter', 'chapter_id': chapters[0].id}),
        ('上一镜头暖光', {'kind': 'targets', 'targets': [request.targets[0].model_dump()]}),
    ]
    for index, (content, scope) in enumerate(scopes):
        await CreationConstraint.create(novel_id=conversation.novel_id, source_message=source,
            fingerprint=f'generation-{index}', content=content, source_quote='合成约束', scope=scope)
    second = await creation_memory.for_generation(chapters[0], [person])
    assert [rule['content'] for rule in second] == ['人物外貌', '第二章晨光']
    assert second[0]['asset_name'] == '林夏'
    assert [rule['content'] for rule in await creation_memory.for_generation(chapters[1], [])] == ['第三章绷带']


@pytest.mark.asyncio
async def test_scoped_memory_does_not_leak_backward_or_to_unrelated_targets():
    conversation, request, source, chapters, scenes = await memory_fixture()
    proposals = [CreationConstraintProposal(content='本场戏保持暖光', source_quote='这场戏都用暖光',
        scope=CreationConstraintScope(kind='targets', targets=[request.targets[0]])),
        CreationConstraintProposal(content='左手保留绷带', source_quote='第三章人物受伤，之后直到第四章都保留左手绷带',
            scope=CreationConstraintScope(kind='range', start_chapter=3, end_chapter=4))]
    saved = await creation_memory.save(source, proposals)
    repeated = await creation_memory.save(source, proposals)
    assert [row.id for row in saved] == [row.id for row in repeated]
    batch = AgentRunRequest(request_id=uuid4(), message='调整这几个镜头', targets=[request.targets[0],
        *[{'kind': 'scene', 'id': scene.id} for scene in scenes]])
    memory = await creation_memory.applicable(conversation.novel_id, batch)
    assert memory[0]['applies_to'] == [request.targets[0].model_dump()]
    assert memory[1]['applies_to'] == [{'kind': 'scene', 'id': scenes[1].id}, {'kind': 'scene', 'id': scenes[2].id}]
    other_conversation = await agent_sessions.create(conversation.novel_id, AuthContext())
    assert other_conversation.id != conversation.id
    assert await creation_memory.applicable(other_conversation.novel_id, batch) == memory
    assert [scene.prompt for scene in await Scene.filter(id__in=[s.id for s in scenes])] == ['合成镜头'] * 3


@pytest.mark.asyncio
async def test_discovered_settings_use_their_story_chapters_not_the_open_page():
    from models.asset import Asset
    from models.asset_variant import AssetVariant

    conversation, request, source, chapters, scenes = await memory_fixture()
    person = await Asset.create(novel_id=conversation.novel_id, canonical_name='林夏', asset_type=1, source_chapters=[2, 3], is_global=False)
    variant = await AssetVariant.create(asset=person, name='绷带', chapter_numbers=[3])
    await scenes[1].assets.add(person)
    for chapter in chapters:
        await CreationConstraint.create(novel_id=conversation.novel_id, source_message=source,
            fingerprint=f'chapter-{chapter.id}', content=f'第{chapter.number}章规则', source_quote='合成约束',
            scope={'kind': 'chapter', 'chapter_id': chapter.id})
    targets = [{'kind': 'asset', 'id': person.id}, {'kind': 'variant', 'id': variant.id}]
    # The user is viewing chapter one while discovering a chapter-three variant.
    rules = await creation_memory.applicable(conversation.novel_id, request.model_copy(update={'targets': []}))
    assert rules == []
    queried = AgentRunRequest(request_id=uuid4(), message='查看该形态', chapter_id=request.chapter_id, targets=targets)
    rules = await creation_memory.applicable(conversation.novel_id, queried)
    assert [(rule['content'], rule['applies_to']) for rule in rules] == [
        ('第2章规则', [targets[0]]), ('第3章规则', targets)]


@pytest.mark.asyncio
async def test_unquoted_inference_and_foreign_scope_are_rejected():
    conversation, request, source, _, _ = await memory_fixture()
    with pytest.raises(ValueError, match='用户明确表达'):
        await creation_memory.save(source, [CreationConstraintProposal(content='女主永远穿红衣', source_quote='女主穿红衣', scope=CreationConstraintScope(kind='project'))])
    with pytest.raises(ValueError, match='已有章节'):
        await creation_memory.save(source, [CreationConstraintProposal(content='绷带', source_quote='人物受伤', scope=CreationConstraintScope(kind='range', start_chapter=3, end_chapter=999))])
    assert await CreationConstraint.filter(novel_id=conversation.novel_id).count() == 0


def test_story_interval_needs_explicit_valid_end_and_disallows_unrelated_scope_fields():
    for scope in ({'kind': 'range', 'start_chapter': 3}, {'kind': 'range', 'start_chapter': 3, 'end_chapter': 1},
                  {'kind': 'chapter'}, {'kind': 'targets'}, {'kind': 'project', 'chapter_id': 3}):
        with pytest.raises(ValidationError):
            CreationConstraintScope.model_validate(scope)


@pytest.mark.asyncio
async def test_explicit_replacement_preserves_source_and_old_history():
    conversation, request, source, _, _ = await memory_fixture()
    scope = CreationConstraintScope(kind='targets', targets=request.targets)
    first = (await creation_memory.save(source, [CreationConstraintProposal(content='暖光', source_quote='暖光', scope=scope)]))[0]
    # A later user request explicitly replaces the exact same scoped constraint.
    source.content = '将刚才的暖光约束改为冷光，只对这个镜头生效。'
    await source.save()
    replacement = CreationConstraintProposal(content='冷光', source_quote='暖光约束改为冷光', scope=scope, supersedes_id=first.id)
    latest = (await creation_memory.save(source, [replacement]))[0]
    assert (await creation_memory.save(source, [replacement]))[0].id == latest.id
    await first.refresh_from_db()
    assert first.superseded_by_id == latest.id
    active = await creation_memory.applicable(conversation.novel_id, request)
    assert len(active) == 1 and active[0]['content'] == '冷光'
    assert await CreationConstraint.filter(novel_id=conversation.novel_id).count() == 2


@pytest.mark.asyncio
async def test_same_memory_proposal_is_idempotent_under_concurrent_delivery():
    _, request, source, _, _ = await memory_fixture()
    proposal = CreationConstraintProposal(content='暖光', source_quote='暖光',
        scope=CreationConstraintScope(kind='targets', targets=request.targets))
    results = await asyncio.gather(*(creation_memory.save(source, [proposal]) for _ in range(2)))
    assert results[0][0].id == results[1][0].id
    assert await CreationConstraint.filter(source_message=source).count() == 1


@pytest.mark.asyncio
async def test_structured_agent_reply_persists_memory_and_emits_user_facing_text(monkeypatch):
    import json
    from pydantic_ai.models.function import FunctionModel, DeltaToolCall
    from services.ai_task_executor import AiTaskExecutor
    from services.creation_agent.handler import CreationAgentTaskHandler
    from utils.enums import AiTaskTypeEnum, TaskStatusEnum

    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'message': '记住，本章都使用暖光。'})
    task = await agent_sessions.submit(conversation, request, AuthContext())
    async def model(messages, info):
        output = info.output_tools[0]
        yield {0: DeltaToolCall(name=output.name, tool_call_id='remember', json_args=json.dumps({
            'message': '已记住，本章后续调整都使用暖光。',
            'constraints': [{'content': '本章使用暖光', 'source_quote': '本章都使用暖光',
                'scope': {'kind': 'chapter', 'chapter_id': request.chapter_id}}],
        }, ensure_ascii=False))}
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args: FunctionModel(stream_function=model))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.completed.value
    assistant = await AgentMessage.get(task=task, role='assistant')
    assert '已记住' in assistant.content
    assert await CreationConstraint.filter(novel_id=conversation.novel_id).count() == 1
    assert any(event['type'] == 'TEXT_MESSAGE_CONTENT' for event in assistant.events)
