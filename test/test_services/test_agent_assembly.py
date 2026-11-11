import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from config import settings
from controllers.chapter import chapter_controller
from controllers.novel import novel_controller
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.config import AiModelConfig
from models.novel import Novel
from models.scene import Scene
from models.ai_task import AiTask
from schemas.chapter import ChapterCreate, ChapterPatch
from services.ai_task_executor import AiTaskExecutor
from services.creation_agent.deep_execution import skill_files
from services.creation_agent.video_optimizer import snapshot_optimizer
from services.reference.handler import AssetReferenceHandler
from services.storyboard.sheets import submit_sheet
from prompts.skill_pack import SkillSnapshot, snapshot_skills
from scripts.export_skill import LINK
from test.test_services.test_creation_agent_sessions import session_fixture
from test.test_services.test_storyboard_handler import _shot
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_managed_episodes_keep_numbers_and_last_deletion_cannot_be_auto_split(monkeypatch):
    novel = await Novel.create(name='分集', content='第一章 原文\n第二章 原文')
    rows = await asyncio.gather(*(chapter_controller.create(ChapterCreate(novel_id=novel.id, name=f'第{i}集', content='导演稿')) for i in range(1, 4)))
    assert sorted(row.number for row in rows) == [1, 2, 3]
    await chapter_controller.remove(next(row.id for row in rows if row.number == 2))
    assert await Chapter.filter(novel=novel).order_by('number').values_list('number', flat=True) == [1, 3]
    for row in await Chapter.filter(novel=novel):
        await chapter_controller.remove(row.id)
    await novel.refresh_from_db()
    assert novel.episodes_managed and novel.total_chapters == 0
    await novel_controller.split(novel.id)
    assert await Chapter.filter(novel=novel).count() == 0
    new = await chapter_controller.create(ChapterCreate(novel_id=novel.id, name='续集', content='新稿'))
    changed = await chapter_controller.patch(new.id, ChapterPatch(name='第1集 新标题', content='新正文'))
    assert (changed.name, changed.content) == ('新标题', '新正文')


@pytest.mark.asyncio
@pytest.mark.parametrize('dependency', ['asset', 'variant', 'archived_scene', 'task'])
async def test_delete_and_renumber_reject_historical_or_pending_dependencies(dependency):
    novel = await Novel.create(name='保护关联')
    chapter = await Chapter.create(novel=novel, number=7, name='第七集', content='稿')
    if dependency in {'asset', 'variant'}:
        asset = await Asset.create(novel=novel, canonical_name='旧角色', asset_type=1,
            source_chapters=['7'] if dependency == 'asset' else [])
        if dependency == 'variant':
            variant = await AssetVariant.create(asset=asset, name='旧衣', chapter_numbers=['7'])
            from datetime import datetime, timezone
            variant.deleted_at = datetime.now(timezone.utc)
            await variant.save()
    elif dependency == 'archived_scene':
        from datetime import datetime, timezone
        await Scene.create(chapter=chapter, sequence=1, deleted_at=datetime.now(timezone.utc))
    else:
        await AiTask.create(task_type=1, status=2, request_params={'novel_id': novel.id, 'chapter_id': chapter.id})
    for action in [chapter_controller.remove(chapter.id), chapter_controller.patch(chapter.id, ChapterPatch(number=8))]:
        with pytest.raises(HTTPException) as error:
            await action
        assert error.value.status_code == 409
    assert await Chapter.filter(id=chapter.id, number=7).exists()


@pytest.mark.asyncio
async def test_deleted_episode_cannot_admit_a_stale_generation_request():
    novel = await Novel.create(name='并发')
    chapter = await Chapter.create(novel=novel, number=1, name='空集', content='')
    await chapter_controller.remove(chapter.id)
    with pytest.raises(ValueError):
        await AiTaskExecutor().submit(AiTaskTypeEnum.extraction, {'novel_id': novel.id, 'chapter_id': chapter.id})
    assert not await AiTask.filter(task_type=1).exists()


def test_three_core_skills_mount_all_shared_links_and_freeze_optional_official_files(tmp_path):
    mounted = skill_files(SkillSnapshot.model_validate(snapshot_skills()))
    for name in ['screenplay', 'assets', 'storyboard']:
        root = f'/skills/novelvids-{name}/'
        entry = mounted[root + 'SKILL.md']
        text = '\n'.join(entry['content'])
        assert all(root + match[2] in mounted for match in LINK.finditer(text))
    profile = snapshot_optimizer('minimax_h3', tmp_path)
    assert profile['mode'] == 'missing'
    root = tmp_path / 'h3-prompt-writing'
    (root / 'references').mkdir(parents=True)
    (root / 'SKILL.md').write_text('Use [base](references/base-en.txt)')
    (root / 'references/base-en.txt').write_text('official rules')
    profile = snapshot_optimizer('minimax_h3', tmp_path)
    assert profile['mode'] == 'optimize' and profile['files']['references/base-en.txt'] == 'official rules'
    (root / 'references/base-en.txt').write_text('later revision')
    assert profile['files']['references/base-en.txt'] == 'official rules'
    assert snapshot_optimizer('unmapped', tmp_path)['mode'] == 'generic'


@pytest.mark.asyncio
async def test_sheet_uses_existing_task_usage_and_preserves_prompt_and_scene_identity(monkeypatch):
    conversation, _, _ = await session_fixture(runtime='deepagents')
    novel = await Novel.get(id=conversation.novel_id)
    novel.storyboard_enabled = True
    await novel.save()
    scene = await Scene.get(chapter__novel_id=novel.id)
    scene.prompt = '已确认的完整视频稿'
    scene.prompt_params = _shot().model_dump()
    await scene.save()
    config = await AiModelConfig.create(task_type=2, name='test-image', model='test-image', image_model_type='gpt_image_2', base_url='https://example.invalid/v1', api_key='test', is_active=True)
    generate = AsyncMock(return_value=[object()])
    monkeypatch.setattr('services.reference.generator.generate_for_sora_consistency', generate)
    monkeypatch.setattr('services.reference.handler._persist_generated_image', AsyncMock(return_value='/media/sheet.png'))
    first, second = await asyncio.gather(submit_sheet(scene.id), submit_sheet(scene.id))
    assert first.id == second.id
    assert first.request_params['model_config_id'] == config.id
    assert 'api_key' not in first.request_params
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.reference_image, AssetReferenceHandler())
    await executor.run(first)
    await first.refresh_from_db()
    assert first.status == TaskStatusEnum.completed, first.error_message
    await scene.refresh_from_db()
    assert scene.prompt == '已确认的完整视频稿'
    assert scene.metadata['storyboard_sheet']['image_url'] == '/media/sheet.png'
    assert first.response_data['image_count'] == 1 and first.response_data['saved']
    assert 'line art storyboard' in generate.call_args.args[0]['base_traits']
    from models.usage_record import ModelUsageRecord
    assert await ModelUsageRecord.filter(ai_task_id=first.id, billing_type='image').count() == 1
    await executor.run(first)
    assert generate.await_count == 1
    assert await Asset.filter(novel=novel).count() == 0


@pytest.mark.asyncio
async def test_sheet_changed_after_submission_never_calls_provider(monkeypatch):
    conversation, _, _ = await session_fixture(runtime='deepagents')
    await Novel.filter(id=conversation.novel_id).update(storyboard_enabled=True)
    scene = await Scene.get(chapter__novel_id=conversation.novel_id)
    scene.prompt_params = _shot().model_dump()
    await scene.save()
    await AiModelConfig.create(task_type=2, name='test-image', model='test-image', image_model_type='gpt_image_2', base_url='https://example.invalid/v1', api_key='test', is_active=True)
    task = await submit_sheet(scene.id)
    await Scene.filter(id=scene.id).update(prompt='新稿')
    generate = AsyncMock()
    monkeypatch.setattr('services.reference.generator.generate_for_sora_consistency', generate)
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.reference_image, AssetReferenceHandler())
    await executor.run(task)
    await task.refresh_from_db()
    assert task.status == TaskStatusEnum.failed
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_episode_business_tool_is_scoped_conflict_checked_and_undoable():
    from types import SimpleNamespace
    from services.creation_agent.changes import CreationChanges
    from services.creation_agent.deep_tools import read_episode_script, revise_episode_script
    from models.creation_agent import AgentMessage
    from schemas.creation_agent import AgentRunRequest, PromptChangeItemOut
    from uuid import uuid4
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'write_scope': 'chapter', 'targets': []})
    task = await AiTask.create(task_type=7, status=2, request_params={'novel_id': conversation.novel_id})
    await AgentMessage.create(task=task, conversation=conversation, role='user', request_id=uuid4(), request_hash='script', run_input=request.model_dump(mode='json'))
    service = CreationChanges(novel_id=conversation.novel_id, task_id=task.id, request=request, max_batch_size=10)
    ctx = SimpleNamespace(deps=SimpleNamespace(changes=service), tool_call_id='episode-update')
    read = await read_episode_script(ctx, request.chapter_id)
    other = await Chapter.create(novel_id=conversation.novel_id, number=2, name='别集', content='不能改')
    await read_episode_script(ctx, other.id)
    with pytest.raises(ValueError):
        await revise_episode_script(ctx, other.id, '越界内容')
    result = await revise_episode_script(ctx, request.chapter_id, '【场景】渡口\n林舟（OS）：灯塔还亮着。', '第1集 回声')
    assert result['status'] == 'saved'
    from models.creation_agent import PromptChange
    change = await PromptChange.get(id=result['change_id'])
    PromptChangeItemOut.model_validate(change.changes[0])
    current = await Chapter.get(id=request.chapter_id)
    assert current.name == '回声' and 'OS' in current.content
    await service.undo(change.id)
    current = await Chapter.get(id=request.chapter_id)
    assert current.content == read['content'] and current.name == read['name']
    await read_episode_script(ctx, current.id)
    await Chapter.filter(id=current.id).update(content='页面并发修改')
    ctx.tool_call_id = 'after-conflict'
    with pytest.raises(ValueError, match='新修改'):
        await revise_episode_script(ctx, current.id, '不能覆盖')


@pytest.mark.asyncio
async def test_project_audiovisual_and_sheet_settings_enter_real_skill_model_request(monkeypatch):
    from types import SimpleNamespace
    from pydantic import BaseModel
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import UserPromptPart
    from services.creation_agent.skill_execution import SkillExecution, prepare_workflow
    from services.creation_agent.production import conversation_for_task
    from unittest.mock import AsyncMock
    conversation, _, _ = await session_fixture()
    await Novel.filter(id=conversation.novel_id).update(audiovisual_guidance='画外对白不入画', storyboard_enabled=True, custom_style_prompt='青灰水墨')
    params = await prepare_workflow({'novel_id': conversation.novel_id, 'prompt_language': 'zh'})
    task = await AiTask.create(task_type=5, status=2, request_params=params)
    message = await conversation_for_task(task)
    class Output(__import__('pydantic').BaseModel):
        result: str
    async def respond(messages, info):
        from pydantic_ai.models.function import DeltaToolCall
        user = next(part.content for m in reversed(messages) for part in m.parts if isinstance(part, UserPromptPart))
        facts = json.loads(user)['untrusted_task_facts']
        assert facts['project']['audiovisual_guidance'] == '画外对白不入画'
        assert facts['project']['storyboard_enabled'] is True
        assert facts['project']['custom_style_prompt'] == '青灰水墨'
        yield {0: DeltaToolCall(name=info.output_tools[0].name, json_args='{"result":"checked"}', tool_call_id='complete')}
    model = FunctionModel(stream_function=respond)
    model.client = AsyncMock()
    monkeypatch.setattr('services.creation_agent.handler.configured_model', lambda *args, **kwargs: model)
    execution = SkillExecution({**params, 'task_id': str(task.id)}, message, AsyncMock())
    assert (await execution.generate('screenplay', {'source': '原文'}, Output)).result == 'checked'


def test_voice_timeline_feedback_identifies_the_missing_separator():
    from services.storyboard.speech_tracks import spoken_parts
    from schemas.scene import SoraScenePromptConfig
    with pytest.raises(ValueError, match='0s-2s'):
        spoken_parts('4.5s-7.0s 阿宁（画外）：我在渡口等你。')
    assert spoken_parts('4.5s-7.0s: 阿宁（画外）：我在渡口等你。') == (4.5, '阿宁', '我在渡口等你。')
    assert '时间后和说话者后都必须有冒号' in SoraScenePromptConfig.model_fields['dialogue'].description


@pytest.mark.asyncio
async def test_cancelling_parent_after_image_request_keeps_usage_without_attaching_image(monkeypatch):
    conversation, _, _ = await session_fixture(runtime='deepagents')
    await Novel.filter(id=conversation.novel_id).update(storyboard_enabled=True)
    scene = await Scene.get(chapter__novel_id=conversation.novel_id)
    scene.prompt_params = _shot().model_dump()
    await scene.save()
    await AiModelConfig.create(task_type=2, name='test-image', model='test-image', image_model_type='gpt_image_2', base_url='https://example.invalid/v1', api_key='test', is_active=True)
    root = await AiTask.create(task_type=3, status=2, request_params={'novel_id': conversation.novel_id})
    task = await submit_sheet(scene.id)
    task.request_params = {**task.request_params, 'origin_run_id': str(root.id)}
    await task.save()
    started, release = asyncio.Event(), asyncio.Event()
    async def generate(*args, **kwargs):
        started.set()
        await release.wait()
        return [object()]
    monkeypatch.setattr('services.reference.generator.generate_for_sora_consistency', generate)
    monkeypatch.setattr('services.reference.handler._persist_generated_image', AsyncMock(return_value='/media/paid-before-stop.png'))
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.reference_image, AssetReferenceHandler())
    work = asyncio.create_task(executor.run(task))
    await asyncio.wait_for(started.wait(), 3)
    await AiTask.filter(id=root.id).update(status=5)
    release.set()
    await work
    await task.refresh_from_db()
    await scene.refresh_from_db()
    assert task.response_data['image_count'] == 1 and not task.response_data['saved']
    assert 'image_url' not in scene.metadata['storyboard_sheet']
    from models.usage_record import ModelUsageRecord
    assert await ModelUsageRecord.filter(ai_task_id=task.id, billing_type='image').count() == 1


def test_official_prompt_rules_cannot_override_the_host_structured_output_contract():
    from services.creation_agent.video_optimizer import optimizer_instructions
    text = optimizer_instructions({'mode': 'optimize', 'skill': 'official', 'files': {'SKILL.md': 'Return only the final plain-text video prompt.'}})
    assert 'TEXT INSIDE the prompt field' in text
    assert text.endswith('Keep the official formatting within the string field.')
    assert 'Return only the final plain-text video prompt.' in text
    assert optimizer_instructions({'mode': 'missing'}) == ''


@pytest.mark.asyncio
async def test_enabled_storyboards_queue_images_without_waiting_for_another_execution_slot(monkeypatch):
    from services.storyboard.handler import StoryboardTaskHandler
    from schemas.scene import Storyboard
    from services.ai_task_executor import ai_task_executor
    novel = await Novel.create(name='单并发故事版', storyboard_enabled=True)
    chapter = await Chapter.create(novel=novel, number=1, name='测试集', content='人物看海')
    scene = await Scene.create(chapter=chapter, sequence=1, prompt='已保存分镜')
    task = await AiTask.create(task_type=2, status=1, request_params={'operation': 'storyboard_sheet'})
    monkeypatch.setattr('services.storyboard.handler.generate_storyboard', AsyncMock(return_value=(Storyboard(shots=[_shot()]), {})))
    monkeypatch.setattr(StoryboardTaskHandler, '_save_scenes', AsyncMock(return_value=[scene]))
    submit = AsyncMock(return_value=task)
    monkeypatch.setattr('services.storyboard.sheets.submit_sheet', submit)
    run = AsyncMock()
    monkeypatch.setattr(ai_task_executor, 'run', run)
    result = await StoryboardTaskHandler().execute({'chapter_id': chapter.id, 'base_url': 'https://example.invalid', 'api_key': 'test', 'model': 'test'})
    assert result['storyboard_sheet_task_ids'] == [str(task.id)]
    assert result['scenes_created'] == 1
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_automatic_sheet_requests_have_independent_idempotency_from_parent_and_siblings():
    from uuid import uuid4
    from services.creation_agent.submissions import submission
    from services.creation_agent.skill_execution import prepare_workflow
    from services.ai_task_executor import ai_task_executor
    conversation, _, _ = await session_fixture(runtime='deepagents')
    await Novel.filter(id=conversation.novel_id).update(storyboard_enabled=True)
    first = await Scene.get(chapter__novel_id=conversation.novel_id)
    first.prompt_params = _shot().model_dump()
    await first.save()
    second = await Scene.create(chapter_id=first.chapter_id, sequence=2, prompt='已保存的第二镜', prompt_params=_shot(2).model_dump())
    await AiModelConfig.create(task_type=2, name='test-image', model='test-image', image_model_type='gpt_image_2', base_url='https://example.invalid/v1', api_key='test', is_active=True)
    token = submission.set({'submission_id': str(uuid4()), 'submission_hash': 'parent-request'})
    try:
        parent = await ai_task_executor.submit(AiTaskTypeEnum.storyboard, await prepare_workflow({'novel_id': conversation.novel_id, 'chapter_id': first.chapter_id}))
        a, b = await submit_sheet(first.id), await submit_sheet(second.id)
        again = await submit_sheet(first.id)
        assert len({parent.id, a.id, b.id}) == 3 and a.id == again.id
        assert a.request_params['submission_id'] != parent.request_params['submission_id']
    finally:
        submission.reset(token)


@pytest.mark.asyncio
async def test_specialist_output_keeps_an_exact_restorable_generic_prompt():
    from services.storyboard.handler import StoryboardTaskHandler
    from schemas.scene import Storyboard
    novel = await Novel.create(name='两稿并存')
    chapter = await Chapter.create(novel=novel, number=1, name='测试集', content='人物看海')
    rows = await StoryboardTaskHandler()._save_scenes(chapter.id, Storyboard(shots=[_shot(visual_prose='风吹过门口。')]), {}, 0,
        optimized_prompts={1: {'model_type': 'test', 'prompt': 'official prompt'}})
    assert rows[0].prompt_params['generic_prompt'] == rows[0].prompt
    assert rows[0].prompt_params['model_optimized_prompt']['prompt'] == 'official prompt'


@pytest.mark.asyncio
async def test_asset_creation_cannot_attach_a_previously_read_deleted_episode(monkeypatch):
    from contextlib import asynccontextmanager
    from controllers.asset import asset_controller
    from controllers._creation import creation_write
    from schemas.asset import AssetCreate
    novel = await Novel.create(name='并发资产绑定')
    chapter = await Chapter.create(novel=novel, number=1, name='第一集', content='正文')
    read, release = asyncio.Event(), asyncio.Event()
    @asynccontextmanager
    async def delayed_lock(novel_id):
        read.set()
        await release.wait()
        async with creation_write(novel_id) as db:
            yield db
    monkeypatch.setattr('controllers.asset.creation_write', delayed_lock)
    work = asyncio.create_task(asset_controller.create(AssetCreate(novel_id=novel.id, chapter_id=chapter.id, asset_type=1, canonical_name='新角色')))
    await asyncio.wait_for(read.wait(), 3)
    await chapter_controller.remove(chapter.id)
    release.set()
    with pytest.raises(HTTPException) as error:
        await work
    assert error.value.status_code == 409
    assert not await Asset.filter(novel=novel).exists()


@pytest.mark.asyncio
async def test_full_script_write_requires_every_page_and_replays_only_identical_calls():
    from services.creation_agent.changes import CreationChanges
    conversation, request, _ = await session_fixture()
    request = request.model_copy(update={'write_scope': 'chapter', 'targets': []})
    task = await AiTask.create(task_type=7, status=2, request_params={'novel_id': conversation.novel_id})
    await Chapter.filter(id=request.chapter_id).update(content='导演稿原文。' * 400)
    service = CreationChanges(novel_id=conversation.novel_id, task_id=task.id, request=request, max_batch_size=10, max_context_characters=2000)
    first = await service.read_episode_script(request.chapter_id)
    assert first['has_more']
    with pytest.raises(ValueError, match='所有分页'):
        await service.revise_episode_script(request.chapter_id, '不能覆盖未读正文', None, 'first')
    page = first
    while page['has_more']:
        page = await service.read_episode_script(request.chapter_id, page['page'] + 1)
    change = await service.revise_episode_script(request.chapter_id, '完整的新导演稿。', None, 'saved')
    again = await service.revise_episode_script(request.chapter_id, '完整的新导演稿。', None, 'saved')
    assert change.id == again.id
    with pytest.raises(ValueError, match='标识'):
        await service.revise_episode_script(request.chapter_id, '同标识不同正文', None, 'saved')
