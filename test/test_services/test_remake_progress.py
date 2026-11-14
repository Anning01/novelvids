import pytest

from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from models.remake_source import RemakeSource
from services.remake.progress import RemakeProgressService
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


async def create_source(novel, episode_number, *, status, stage, progress):
    chapter = await Chapter.create(
        novel=novel,
        number=episode_number,
        name=f"第{episode_number}集",
        content="",
    )
    task = await AiTask.create(
        task_type=AiTaskTypeEnum.remake_decomposition.value,
        status=status,
        stage=stage,
        progress=progress,
    ) if status is not None else None
    return await RemakeSource.create(
        novel=novel,
        chapter=chapter,
        episode_number=episode_number,
        source_kind="upload",
        storage_provider="local",
        object_key=f"remake/{episode_number}.mp4",
        original_filename=f"第{episode_number}集.mp4",
        mime_type="video/mp4",
        size_bytes=1024,
        duration_seconds=12,
        width=1080,
        height=1920,
        container_format="mp4",
        checksum=str(episode_number) * 64,
        media_status="processing",
        analysis_task=task,
    )


@pytest.mark.asyncio
async def test_project_progress_is_recoverable_from_persisted_tasks():
    novel = await Novel.create(
        name="进度快照项目",
        author="重制工坊",
        workflow_kind="remake",
    )
    await create_source(
        novel,
        1,
        status=TaskStatusEnum.completed.value,
        stage="completed",
        progress=100,
    )
    await create_source(
        novel,
        2,
        status=TaskStatusEnum.running.value,
        stage="detecting_scenes",
        progress=42,
    )

    snapshot = await RemakeProgressService().snapshot(novel)

    assert snapshot["aggregate_status"] == "processing"
    assert snapshot["terminal"] is False
    assert snapshot["overall_progress"] == 71
    assert snapshot["source_summary"] == {
        "total": 2,
        "queued": 0,
        "processing": 1,
        "completed": 1,
        "failed": 0,
    }
    assert snapshot["sources"][1]["task"]["stage"] == "detecting_scenes"
    assert snapshot["entry_path"].endswith(str(novel.id))


@pytest.mark.asyncio
async def test_project_progress_becomes_terminal_when_every_source_finishes():
    novel = await Novel.create(
        name="已完成进度项目",
        author="重制工坊",
        workflow_kind="remake",
    )
    await create_source(
        novel,
        1,
        status=TaskStatusEnum.completed.value,
        stage="completed",
        progress=99,
    )

    snapshot = await RemakeProgressService().snapshot(novel)

    assert snapshot["aggregate_status"] == "completed"
    assert snapshot["terminal"] is True
    assert snapshot["overall_progress"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize('media_status,task_status,expected', [
    ('completed', None, 'completed'),
    ('ready', None, 'queued'),
    ('processing', None, 'queued'),
    ('completed', TaskStatusEnum.running.value, 'processing'),
    ('completed', TaskStatusEnum.failed.value, 'failed'),
])
async def test_imported_completed_source_does_not_require_an_analysis_task(media_status, task_status, expected):
    novel = await Novel.create(name='Imported remake', workflow_kind='remake')
    source = await create_source(novel, 1, status=task_status, stage='queued', progress=0)
    source.media_status = media_status
    await source.save(update_fields=['media_status'])
    before = await AiTask.all().count()
    snapshot = await RemakeProgressService().snapshot(novel)
    assert snapshot['aggregate_status'] == expected
    assert snapshot['overall_progress'] == (100 if expected == 'completed' else 0)
    assert snapshot['terminal'] is (expected in {'completed', 'failed'})
    if task_status is None:
        assert snapshot['sources'][0]['task'] is None
    assert await AiTask.all().count() == before


@pytest.mark.asyncio
async def test_failed_clip_progress_explains_verified_saved_work_and_next_action():
    from uuid import uuid5
    from models.agent_operation import AgentOperation
    from models.creation_agent import AgentConversation, AgentMessage
    novel = await Novel.create(name='进度说明', workflow_kind='remake')
    source = await create_source(novel, 1, status=4, stage='generating_storyboards', progress=55)
    task = await source.analysis_task
    task.error_message = '第 5 个视频片段分析失败：本次任务的增量修复已用完，候选和调用记录已保留，请核对失败步骤。'
    await task.save()
    child = await AiTask.create(id=uuid5(task.id, 'model:remake:RemakeShot:5'), task_type=7,status=4)
    conversation = await AgentConversation.create(novel=novel)
    await AgentMessage.create(conversation=conversation, task=child,role='assistant',request_id=child.id,
        request_hash='test',native_messages=[{'parts':[{'part_kind':'retry-prompt','content':[{
            'msg':'Value error, Shot and layout must share the same orientation','input':'private payload'}]}]}])
    for key in ['RemakeAssets:1','RemakeShot:1','RemakeShot:3','RemakeShot:10']:
        await AgentOperation.create(task=task,key='model:remake:'+key,state='completed')
    text = (await RemakeProgressService().snapshot(novel))['sources'][0]['task']['error_message']
    assert '第 5 个片段' in text and '底图方向' in text and '已保留 3 个片段' in text and '「重试」' in text
    assert '增量修复' not in text and 'private payload' not in text


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,diagnostic,expected', [
    ('needs_review', 'raw provider body', '以免重复扣费'),
    ('extracting_assets','unauthorized（错误代码：REMAKE_ANALYSIS_AUTH_FAILED）','管理员检查模型密钥'),
    ('generating_storyboards','第 2 个视频片段分析失败：private payload','第 2 个片段未能完成分镜分析'),
])
async def test_progress_only_displays_safe_actionable_copy(stage, diagnostic, expected):
    novel = await Novel.create(name='失败说明',workflow_kind='remake')
    source = await create_source(novel,1,status=4,stage=stage,progress=20)
    await AiTask.filter(id=source.analysis_task_id).update(error_message=diagnostic)
    text = (await RemakeProgressService().snapshot(novel))['sources'][0]['task']['error_message']
    assert expected in text and diagnostic not in text


@pytest.mark.asyncio
async def test_receipt_on_failed_clip_displays_acceptance_and_keeps_completed_count(monkeypatch):
    from models.agent_operation import AgentOperation
    novel = await Novel.create(name='回执', workflow_kind='remake')
    source = await create_source(novel,1,status=4,stage='needs_review',progress=59)
    await AgentOperation.create(task_id=source.analysis_task_id, key='model:remake:RemakeShot:1',state='completed',result={})
    from unittest.mock import AsyncMock
    monkeypatch.setattr('services.remake.progress.accepted_shots_awaiting_result',AsyncMock(return_value=[14,16]))
    task = (await RemakeProgressService().snapshot(novel))['sources'][0]['task']
    assert task['awaiting_platform_result']
    assert '已保留 1 个片段' in task['error_message'] and '14, 16' in task['error_message']


@pytest.mark.asyncio
async def test_restart_queues_remake_from_saved_clips_and_refresh_keeps_position(tmp_path, monkeypatch):
    from models.agent_operation import AgentOperation
    from services.creation_agent.recovery import ProductionRecovery
    from services.remake.checkpoints import write_scene_manifest

    novel = await Novel.create(name='断点恢复',workflow_kind='remake')
    source = await create_source(novel,1,status=2,stage='generating_storyboards',progress=55)
    task = await source.analysis_task
    task.request_params = {'workflow_version':'agent-skills-v1','remake_source_id':source.id,'novel_id':novel.id}
    await task.save()
    monkeypatch.setattr('services.remake.checkpoints.scene_cache_directory',lambda _:tmp_path)
    files = [tmp_path / f'{i}.mp4' for i in range(4)]
    for path in files:
        path.write_bytes(b'clip')
    write_scene_manifest(tmp_path,files,[1.0]*4)
    for key in ['RemakeAssets:1','RemakeShot:1','RemakeShot:3']:
        await AgentOperation.create(task=task,key='model:remake:'+key,state='completed')
    await ProductionRecovery().recover()
    await task.refresh_from_db()
    assert (task.status,task.stage,task.progress) == (6,'generating_storyboards',71)
    snapshot = (await RemakeProgressService().snapshot(novel))['sources'][0]['task']
    assert (snapshot['progress'],snapshot['completed_clips'],snapshot['total_clips']) == (71,2,4)


@pytest.mark.asyncio
async def test_partial_retry_inherits_uncertain_shots_and_counts_only_unsubmitted(tmp_path, monkeypatch):
    from models.agent_operation import AgentOperation
    from services.remake.checkpoints import partial_retry, write_scene_manifest
    novel = await Novel.create(name='片段续跑', workflow_kind='remake')
    source = await create_source(novel,1,status=4,stage='needs_review',progress=59)
    task = await source.analysis_task
    task.request_params = {'held_shots':[2]}
    await task.save()
    monkeypatch.setattr('services.remake.checkpoints.scene_cache_directory',lambda _:tmp_path)
    files = [tmp_path / f'{i}.mp4' for i in range(4)]
    for path in files:
        path.write_bytes(b'clip')
    write_scene_manifest(tmp_path,files,[1.0]*4)
    for suffix in ['RemakeAssets:1','RemakeShot:1']:
        await AgentOperation.create(task=task,key='model:remake:'+suffix,state='completed')
    await AgentOperation.create(task=task,key='model:remake:RemakeShot:3',state='uncertain',external=True)
    assert await partial_retry(task,4) == ([2,3],1)
    snapshot = (await RemakeProgressService().snapshot(novel))['sources'][0]['task']
    assert snapshot['retryable_clips'] == 1
    await AgentOperation.create(task=task,key='model:remake:RemakeShot:4',state='completed')
    assert await partial_retry(task,4) == ([2,3],0)
