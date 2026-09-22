import pytest

from auth.deps import AuthContext
from models.creation_agent import AgentMessage, CreationConstraint, PromptChange
from models.scene import Scene
from schemas.creation_agent import PromptStatusRequest, StoryboardPromptEdit
from services.creation_agent.memory import creation_memory
from services.creation_agent.sessions import agent_sessions
from services.creation_agent.tools import PromptEditService, prompt_version
from test.test_services.test_creation_agent_sessions import session_fixture
from utils.enums import TaskStatusEnum


async def status_fixture():
    conversation, request, _ = await session_fixture()
    task = await agent_sessions.submit(conversation, request, AuthContext())
    await type(task).filter(id=task.id).update(status=TaskStatusEnum.running.value)
    source = await AgentMessage.get(task=task, role='user')
    scene = await Scene.get(id=request.targets[0].id)
    other = await Scene.create(chapter_id=scene.chapter_id, sequence=2, prompt='B冷光', duration=6)
    constraint = await CreationConstraint.create(novel_id=conversation.novel_id, source_message=source,
        fingerprint='status-rule', content='只让A使用暖光', source_quote='暖光',
        scope={'kind': 'targets', 'targets': [request.targets[0].model_dump()]})
    status_request = PromptStatusRequest(chapter_id=request.chapter_id,
        targets=[request.targets[0], {'kind': 'scene', 'id': other.id}])
    async def context():
        return await creation_memory.applicable(conversation.novel_id, request)
    service = PromptEditService(novel_id=conversation.novel_id, task_id=task.id,
        allowed_targets={('scene', scene.id)}, max_batch_size=2, context_check=context)
    return conversation, status_request, scene, other, constraint, service


@pytest.mark.asyncio
async def test_pending_rules_are_scoped_and_cleared_only_for_current_recorded_edit():
    conversation, request, scene, other, rule, service = await status_fixture()
    async def statuses():
        return await creation_memory.prompt_status(conversation.novel_id, request)
    original = await statuses()
    assert original[0]['pending_constraints'] == [{'id': rule.id, 'content': rule.content}]
    assert original[1]['pending_constraints'] == []
    await scene.refresh_from_db()
    assert scene.prompt == '空站台' and other.prompt == 'B冷光'
    change = await service.update_storyboard_prompt([StoryboardPromptEdit(scene_id=scene.id,
        expected_version=prompt_version(scene), legacy_prompt='A站台灯光温暖。')], tool_call_id='apply')
    assert change.changes[0]['constraint_ids'] == [rule.id]
    assert (await statuses())[0]['pending_constraints'] == []
    await service.undo(change.id)
    assert (await statuses())[0]['pending_constraints'] == original[0]['pending_constraints']
    await scene.refresh_from_db()
    assert scene.prompt == '空站台'


@pytest.mark.asyncio
async def test_crud_receipts_compare_prompt_fields_and_ignore_later_order_only_changes():
    from schemas.creation_agent import AgentRunRequest
    from schemas.creation_objects import CreationChangeSet
    from services.creation_agent.changes import CreationChanges

    conversation, request, scene, _, rule, legacy = await status_fixture()
    changes = CreationChanges(novel_id=conversation.novel_id, task_id=legacy.task_id,
        request=AgentRunRequest(request_id=legacy.task_id, message='调整暖光和描述',
            chapter_id=scene.chapter_id, write_scope='chapter'), max_batch_size=8)
    await changes.read([request.targets[0]])
    await changes.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_scene', 'scene_id': scene.id,
        'fields': {'prompt': '暖黄灯光照亮独立完整的站台。', 'description': '暖光站台'},
    }]}), tool_call_id='crud-prompt')
    assert (await creation_memory.prompt_status(conversation.novel_id, request))[0]['pending_constraints'] == []
    await changes.apply(CreationChangeSet.model_validate({'operations': [{
        'operation': 'update_scene', 'scene_id': scene.id, 'fields': {'after': None},
    }]}), tool_call_id='reorder-only')
    assert (await creation_memory.prompt_status(conversation.novel_id, request))[0]['pending_constraints'] == []


@pytest.mark.asyncio
async def test_pending_status_uses_recorded_rules_with_production_timezone(monkeypatch):
    from tortoise.timezone import _reset_timezone_cache

    try:
        with monkeypatch.context() as patch:
            patch.setenv('USE_TZ', 'True')
            patch.setenv('TIMEZONE', 'Asia/Shanghai')
            _reset_timezone_cache()
            conversation, request, scene, _, rule, service = await status_fixture()
            await service.update_storyboard_prompt([StoryboardPromptEdit(scene_id=scene.id,
                expected_version=prompt_version(scene), legacy_prompt='暖光照亮站台。')], tool_call_id='timezone')
            # Production stores UTC timestamps and returns local aware datetimes.
            loaded_rule = await CreationConstraint.get(id=rule.id)
            assert loaded_rule.created_at.utcoffset().total_seconds() == 8 * 3600
            statuses = await creation_memory.prompt_status(conversation.novel_id, request)
            assert statuses[0]['pending_constraints'] == []
    finally:
        _reset_timezone_cache()


@pytest.mark.asyncio
async def test_manual_edit_and_replaced_constraint_require_rechecking():
    conversation, request, scene, _, rule, service = await status_fixture()
    change = await service.update_storyboard_prompt([StoryboardPromptEdit(scene_id=scene.id,
        expected_version=prompt_version(scene), legacy_prompt='暖光照亮站台。')], tool_call_id='apply')
    await Scene.filter(id=scene.id).update(prompt='用户改成其他内容')
    assert (await creation_memory.prompt_status(conversation.novel_id, request))[0]['pending_constraints']
    await Scene.filter(id=scene.id).update(**change.changes[0]['after'])
    replacement = await CreationConstraint.create(novel_id=conversation.novel_id, source_message_id=rule.source_message_id,
        fingerprint='replacement', content='只让A使用冷光', source_quote='冷光', scope=rule.scope, supersedes_id=rule.id)
    rule.superseded_by_id = replacement.id
    await rule.save()
    pending = (await creation_memory.prompt_status(conversation.novel_id, request))[0]['pending_constraints']
    assert pending == [{'id': replacement.id, 'content': replacement.content}]


@pytest.mark.asyncio
async def test_legacy_record_without_rule_snapshot_never_silently_clears_pending():
    conversation, request, scene, _, _, service = await status_fixture()
    change = await service.update_storyboard_prompt([StoryboardPromptEdit(scene_id=scene.id,
        expected_version=prompt_version(scene), legacy_prompt='暖光照亮站台。')], tool_call_id='legacy')
    change.changes[0].pop('constraint_ids')
    await change.save()
    assert (await creation_memory.prompt_status(conversation.novel_id, request))[0]['pending_constraints']


@pytest.mark.asyncio
async def test_status_api_is_read_only_bounded_and_rejects_foreign_targets(client):
    conversation, request, scene, _, _, _ = await status_fixture()
    before = await PromptChange.all().count()
    url = f'/api/creation-agent/prompt-status?novel_id={conversation.novel_id}'
    response = await client.post(url, json=request.model_dump())
    assert response.json()['code'] == 0
    assert response.json()['data'][0]['pending_constraints']
    assert 'source_quote' not in response.text and 'source_message' not in response.text
    assert await PromptChange.all().count() == before
    assert (await Scene.get(id=scene.id)).prompt == '空站台'
    from models.novel import Novel
    from models.chapter import Chapter
    foreign = await Novel.create(name="其他状态项目")
    chapter = await Chapter.create(novel=foreign, number=1, name="其他章", content="合成正文")
    foreign_scene = await Scene.create(chapter=chapter, sequence=1)
    response = await client.post(url, json={'targets': [{'kind': 'scene', 'id': foreign_scene.id}]})
    assert response.json()['code'] == 404
    response = await client.post(url, json={'targets': [request.targets[0].model_dump()] * 101})
    assert response.json()['code'] == 422
