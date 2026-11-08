import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from controllers.novel import novel_controller
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.chapter import Chapter
from models.creation_agent import AgentConversation, AgentMessage
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from models.usage_record import ModelUsageRecord
from services.ai_task_executor import ai_task_executor
from utils.enums import AiTaskTypeEnum

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('stage', ['needs_review', 'billing_pending'])
async def test_deletion_is_independent_of_audit_and_settlement(stage):
    from models.creation_agent import AgentEvent
    project, task = await project_task(status=4)
    await AiTask.filter(id=task.id).update(stage=stage)
    receipt = await AgentOperation.create(task=task, key='model:remake', state='uncertain', external=True)
    conversation = await AgentConversation.create(novel=project)
    message = await AgentMessage.create(conversation=conversation, task=task, request_id=task.id,
        request_hash='retained', role='assistant', native_messages=[{'evidence': 'original'}],
        usage={'calls': [{'status': 'failed', 'usage_reported': False}]})
    event = await AgentEvent.create(message=message, seq=1, event={'type': 'RUN_ERROR'})
    record = await ModelUsageRecord.create(novel_id=project.id, ai_task_id=task.id,
        task_type=5, billing_type='text', model='recorded', cost='1.25', usage={'missing_usage': True})

    await novel_controller.remove(project.id)

    assert not await Novel.filter(id=project.id).exists()
    assert (await Novel.with_deleted().get(id=project.id)).deleted_at is not None
    await task.refresh_from_db()
    await receipt.refresh_from_db()
    await message.refresh_from_db()
    await record.refresh_from_db()
    assert task.stage == stage and receipt.state == 'uncertain'
    assert message.native_messages == [{'evidence': 'original'}]
    assert record.cost == Decimal('1.25') and record.usage == {'missing_usage': True}
    assert await AgentEvent.filter(id=event.id).exists()
    assert not (await novel_controller.overview()).items


async def test_deleted_project_rejects_late_writes_and_releases_its_title():
    project, _ = await project_task(status=4)
    title = project.name
    await novel_controller.remove(project.id)
    project.content = 'late model response'
    with pytest.raises(ValueError, match='项目不存在'):
        await project.save()
    replacement = await Novel.create(name=title)
    assert replacement.id != project.id


async def test_deleted_project_keeps_task_review_access_but_blocks_creative_access(monkeypatch):
    from auth.deps import AuthContext, ensure_novel_access, require_task_access
    from config import settings
    from schemas.ai_task import TaskReviewResolution
    from services.creation_agent.review import close_uncertain_task
    project, task = await project_task(status=4)
    await AiTask.filter(id=task.id).update(stage='needs_review')
    await AgentOperation.create(task=task, key='model:remake', state='uncertain', external=True)
    await novel_controller.remove(project.id)
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)
    with pytest.raises(HTTPException) as error:
        await ensure_novel_access(project.id, AuthContext())
    assert error.value.status_code == 404
    await require_task_access(task.id, AuthContext())
    reviewed = await close_uncertain_task(task.id, TaskReviewResolution(outcome='provider_failed', note='Provider confirmed failure'))
    assert reviewed.stage == 'review_closed'


async def test_deleted_project_audit_remains_team_scoped_and_child_calls_remain_private(monkeypatch):
    from auth.deps import AuthContext, require_task_access
    from config import settings
    monkeypatch.setattr(settings, 'AUTH_ENABLED', True)
    project = await Novel.create(name='deleted-private-audit', team_id=2, created_by=3)
    task = await AiTask.create(task_type=6, status=4, request_params={'novel_id': project.id, 'team_id': 2})
    child = await AiTask.create(task_type=7, status=4, request_params={'novel_id': project.id, 'parent_task_id': str(task.id)})
    conversation = await AgentConversation.create(novel=project, team_id=2, created_by=3)
    await AgentMessage.create(conversation=conversation, task=child, request_id=child.id,
        request_hash='private-audit', role='assistant')
    await novel_controller.remove(project.id)
    owner = AuthContext(user=SimpleNamespace(id=3), team_id=2)
    await require_task_access(task.id, owner)
    await require_task_access(child.id, owner)
    for target, ctx in (
        (task.id, AuthContext(user=SimpleNamespace(id=4), team_id=4)),
        (child.id, AuthContext(user=SimpleNamespace(id=4), team_id=2)),
    ):
        with pytest.raises(HTTPException) as error:
            await require_task_access(target, ctx)
        assert error.value.status_code == 404


async def test_delete_api_removes_workspace_but_keeps_billing_and_task_reads(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)
    project, task = await project_task(status=4)
    chapter = await Chapter.create(novel=project, number=1, name='one', content='story')
    await AiTask.filter(id=task.id).update(stage='needs_review')
    await AgentOperation.create(task=task, key='model:remake', external=True, state='uncertain')
    await ModelUsageRecord.create(novel_id=project.id, ai_task_id=task.id,
        task_type=5, billing_type='text', model='recorded', cost='1.25')
    removed = await client.delete(f'/api/novel/{project.id}')
    assert removed.json()['code'] == 0
    for path in (f'/api/novel/{project.id}', f'/api/chapter/{chapter.id}'):
        assert (await client.get(path)).json()['code'] == 404
    assert (await client.get(f'/api/task/{task.id}')).json()['code'] == 0
    billing = (await client.get(f'/api/billing/projects/{project.id}')).json()
    assert billing['code'] == 0 and billing['data']['total_cost'] == 1.25
    assert '已删除' in billing['data']['novel_name']


async def test_video_usage_can_settle_once_after_project_deletion(monkeypatch):
    from config import settings
    from models.config import AiModelConfig
    from services.creation_agent.video_settlement import settle_video
    monkeypatch.setattr(settings, 'AUTH_ENABLED', False)
    project, task = await project_task(status=5)
    chapter = await Chapter.create(novel=project, number=1, name='one', content='story')
    scene = await Scene.create(chapter=chapter, sequence=1)
    config = await AiModelConfig.create(name='deleted-video-model', task_type=4, model='video',
        api_key='synthetic', base_url='https://example.invalid', is_active=True,
        video_model_type='seedance_2', pricing={'type': 'video', 'currency': 'CNY', 'prices': {'720p': 46}})
    video = await Video.create(scene=scene, model_type=1, status=3, external_task_id='accepted-before-delete',
        metadata={'agent_run_id': str(task.id), 'novel_id': project.id, 'model_config_id': config.id,
            'resolution': '720p', 'provider_accounting': {'seconds': 5, 'status': 3,
                'usage_reported': True, 'reported_seconds': 5}})
    task.request_params['video_id'] = video.id
    await task.save(update_fields=['request_params'])
    await novel_controller.remove(project.id)
    await settle_video(video)
    await settle_video(video)
    records = await ModelUsageRecord.filter(novel_id=project.id, video_id=video.id)
    assert len(records) == 1 and records[0].cost > 0
    assert records[0].usage['usage_known'] is True
    assert (await AgentOperation.get(task=task, key='billing:video')).state == 'completed'
    await video.refresh_from_db()
    assert video.metadata['billing_pending'] is False
    assert not await Novel.filter(id=project.id).exists()


async def project_task(status=1, **extra):
    project = await Novel.create(name='deletion-boundary')
    task = await AiTask.create(task_type=5, status=status, started_at=datetime.now(timezone.utc) if status==2 else None, request_params={'novel_id':project.id, **extra})
    return project,task


async def test_queued_work_is_stopped_before_project_deletion(monkeypatch):
    project,task=await project_task()
    await novel_controller.remove(project.id)
    assert not await Novel.filter(id=project.id).exists()
    await task.refresh_from_db()
    assert task.status==5
    handler=AsyncMock()
    monkeypatch.setitem(ai_task_executor._handlers,AiTaskTypeEnum.project_analysis,handler)
    await ai_task_executor.run(task)
    handler.execute.assert_not_awaited()


async def test_cancelled_request_can_settle_after_project_deletion(monkeypatch):
    project,task=await project_task(status=2)
    lock=asyncio.Lock();await lock.acquire()
    monkeypatch.setitem(ai_task_executor._task_locks,str(task.id),lock)
    await novel_controller.remove(project.id)
    await task.refresh_from_db()
    assert task.status==5 and not await Novel.filter(id=project.id).exists()
    record=await ModelUsageRecord.create(novel_id=project.id,task_type=5,billing_type='text',model='recorded',cost=Decimal('1.25'),ai_task_id=task.id)
    lock.release()
    assert await ModelUsageRecord.filter(id=record.id,cost=Decimal('1.25')).exists()


async def test_model_child_and_its_usage_are_preserved_until_charged():
    project,parent=await project_task(status=2)
    conversation=await AgentConversation.create(novel=project)
    child=await AiTask.create(task_type=7,status=2,request_params={'parent_task_id':str(parent.id)})
    message=await AgentMessage.create(conversation=conversation,task=child,request_id=child.id,request_hash='hash',role='assistant',usage={'calls':[{'input_tokens':10,'output_tokens':2}]})
    await novel_controller.remove(project.id)
    await child.refresh_from_db()
    assert child.status==2
    await AiTask.filter(id=child.id).update(status=3)
    assert not await Novel.filter(id=project.id).exists()
    assert await AgentMessage.filter(id=message.id).exists()
    record=await ModelUsageRecord.create(novel_id=project.id,task_type=7,billing_type='text',model='recorded',cost='0.1',ai_task_id=child.id)
    await AgentMessage.filter(id=message.id).update(billing_record_id=record.id)
    assert await ModelUsageRecord.filter(id=record.id).exists()


@pytest.mark.parametrize('stage',['billing_pending','needs_review'])
async def test_unsettled_or_uncertain_tasks_do_not_block_deletion(stage):
    project,task=await project_task(status=4)
    await AiTask.filter(id=task.id).update(stage=stage)
    await novel_controller.remove(project.id)
    assert not await Novel.filter(id=project.id).exists()
    await task.refresh_from_db()
    assert task.stage == stage


async def test_external_request_evidence_is_not_deleted():
    project,task=await project_task(status=4)
    receipt=await AgentOperation.create(task=task,key='media:cover',state='uncertain',external=True)
    await novel_controller.remove(project.id)
    assert await AgentOperation.filter(id=receipt.id).exists()


async def test_submitted_video_keeps_callback_target_after_project_deletion():
    project=await Novel.create(name='submitted-video')
    chapter=await Chapter.create(novel=project,number=1,name='one',content='story')
    scene=await Scene.create(chapter=chapter,sequence=1)
    video=await Video.create(scene=scene,model_type=1,status=2,external_task_id='provider-job')
    await novel_controller.remove(project.id)
    assert not await Novel.filter(id=project.id).exists()
    assert await Video.filter(id=video.id,external_task_id='provider-job').exists()


async def test_legacy_chapter_scope_is_stopped_without_touching_other_projects():
    project=await Novel.create(name='legacy-owner')
    chapter=await Chapter.create(novel=project,number=1,name='one',content='story')
    task=await AiTask.create(task_type=1,status=1,request_params={'chapter_id':chapter.id})
    other=await AiTask.create(task_type=1,status=1,request_params={'novel_id':project.id+100})
    await novel_controller.remove(project.id)
    await task.refresh_from_db();await other.refresh_from_db()
    assert task.status==5 and other.status==1


async def test_deleted_project_cannot_admit_another_paid_task():
    project=await Novel.create(name='deleted-before-submit')
    await novel_controller.remove(project.id)
    with pytest.raises(ValueError,match='项目不存在'):
        await ai_task_executor.submit(AiTaskTypeEnum.project_analysis,{'novel_id':project.id})
    assert not await AiTask.all().exists()


@pytest.mark.parametrize('cancel_during',['analysis','cover'])
async def test_delete_during_paid_call_stops_future_cover_and_keeps_actual_charges(monkeypatch,cancel_during):
    from models.config import AiModelConfig
    from services.project_analysis.handler import ProjectAnalysisTaskHandler,BookAnalysis
    project=await Novel.create(name='selected-wrong-project',content='第一章 清晨\n少年醒来。')
    await Chapter.create(novel=project,number=1,name='清晨',content='少年醒来。')
    await AiModelConfig.create(name='analysis-model',task_type=5,model='mock-text',base_url='https://example.invalid',api_key='test',is_active=True,
        pricing={'type':'text','currency':'CNY','input_price_per_1m':10,'output_price_per_1m':20})
    await AiModelConfig.create(name='cover-model',task_type=2,model='mock-image',base_url='https://example.invalid',api_key='test',is_active=True,image_model_type='seedream_5_pro',api_protocol='volcengine_ark',
        pricing={'type':'image','currency':'CNY','prices':{'1K':0.3,'1.5K':0.3,'2K':0.3}})
    task=await AiTask.create(task_type=5,status=1,request_params={'novel_id':project.id})
    async def delete_while_provider_is_busy():
        await novel_controller.remove(project.id)
        assert not await Novel.filter(id=project.id).exists()
    async def text_call(*args,**kwargs):
        if cancel_during=='analysis':await delete_while_provider_is_busy()
        return BookAnalysis(book_types=['科幻'],story_outline='少年在清晨醒来。',key_characters=[]),SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20,total_tokens=120))
    async def image_call(**kwargs):
        await delete_while_provider_is_busy()
        return [SimpleNamespace(url='https://example.invalid/cover.png',b64_json=None)]
    image=AsyncMock(side_effect=image_call)
    monkeypatch.setattr('services.project_analysis.handler.create_json_completion',AsyncMock(side_effect=text_call))
    monkeypatch.setattr('services.project_analysis.handler.generate_images',image)
    monkeypatch.setattr('services.project_analysis.handler._save_cover',AsyncMock(return_value='/media/example-cover.png'))
    monkeypatch.setitem(ai_task_executor._handlers,AiTaskTypeEnum.project_analysis,ProjectAnalysisTaskHandler())
    await ai_task_executor.run(task)
    await task.refresh_from_db()
    assert task.status==5
    assert image.await_count==(1 if cancel_during=='cover' else 0)
    records=await ModelUsageRecord.filter(novel_id=project.id)
    assert sum(record.cost for record in records if record.billing_type=='text')==Decimal('0.0014')
    assert sum(record.cost for record in records if record.billing_type=='image')==(Decimal('0.3') if cancel_during=='cover' else 0)
    assert not await Novel.filter(id=project.id).exists()
    assert await ModelUsageRecord.filter(novel_id=project.id).count()==len(records)


async def test_cancelled_uncertain_request_remains_available_for_manual_review():
    project,task=await project_task(status=5)
    await AgentOperation.create(task=task,key='media:cover',state='uncertain',external=True)
    await novel_controller.remove(project.id)
    await task.refresh_from_db()
    assert task.status==4 and task.stage=='needs_review'


async def test_completed_task_cannot_lose_usage_before_executor_releases_its_lease(monkeypatch):
    project,task=await project_task(status=2)
    await AiTask.filter(id=task.id).update(status=3)
    lock=asyncio.Lock();await lock.acquire()
    monkeypatch.setitem(ai_task_executor._task_locks,str(task.id),lock)
    await novel_controller.remove(project.id)
    lock.release()
    assert not await Novel.filter(id=project.id).exists()
    assert await AiTask.filter(id=task.id, status=3).exists()


async def test_unstarted_queue_wait_does_not_delay_safe_deletion(monkeypatch):
    project,task=await project_task(status=1)
    lock=asyncio.Lock();await lock.acquire()
    monkeypatch.setitem(ai_task_executor._task_locks,str(task.id),lock)
    try:await novel_controller.remove(project.id)
    finally:lock.release()
    assert not await Novel.filter(id=project.id).exists()


async def test_pending_video_accounting_cannot_be_removed_with_completed_video():
    project=await Novel.create(name='video-accounting')
    chapter=await Chapter.create(novel=project,number=1,name='one',content='story')
    scene=await Scene.create(chapter=chapter,sequence=1)
    await Video.create(scene=scene,model_type=1,status=3,metadata={'billing_pending':True})
    await novel_controller.remove(project.id)
    assert not await Novel.filter(id=project.id).exists()
    assert await Video.filter(scene=scene, metadata={'billing_pending': True}).exists()


async def test_completed_usage_and_team_balance_are_not_refunded_by_deletion(monkeypatch):
    from auth.models import Team,TeamMember,User,BalanceTransaction
    from config import settings
    from services.billing.recorder import _consume_team_balance
    from services.billing.aggregation import project_detail
    monkeypatch.setattr(settings,'AUTH_ENABLED',True)
    team=await Team.create(name='settled-project',balance='10')
    user=await User.create(username='settled-project-owner')
    member=await TeamMember.create(team=team,user=user,role='creator')
    project=await Novel.create(name='settled-project',team_id=team.id,created_by=user.id)
    record=await ModelUsageRecord.create(novel_id=project.id,team_id=team.id,user_id=user.id,task_type=5,billing_type='text',model='recorded',cost='1.25')
    await _consume_team_balance(record,team.id,user_id=user.id)
    await novel_controller.remove(project.id)
    await team.refresh_from_db();await member.refresh_from_db()
    assert team.balance==Decimal('8.75') and member.total_cost==Decimal('1.25')
    assert await BalanceTransaction.filter(team=team,usage_record_id=record.id).count()==1
    detail=await project_detail(project.id,team_id=team.id)
    assert detail['total_cost']==1.25 and detail['record_count']==1 and '已删除' in detail['novel_name']


async def test_external_export_receipt_survives_deletion_attempt():
    from models.chapter_export import ChapterExport
    project=await Novel.create(name='pending-enhancement')
    export=await ChapterExport.create(novel_id=project.id,chapter_id=1,identity_key='pending-enhancement',source_version='one',provider_task_id='submitted-enhancement',collection_complete=False)
    await novel_controller.remove(project.id)
    assert await ChapterExport.filter(id=export.id).exists()


async def test_uncertain_failure_after_cancellation_is_reviewable(monkeypatch):
    project,task=await project_task(status=5,workflow_version='agent-skills-v1')
    await AgentOperation.create(task=task,key='media:cover',state='uncertain',external=True)
    monkeypatch.setattr('services.creation_agent.production.finish_production_message',AsyncMock())
    await ai_task_executor._fail(task,'provider outcome unknown',record_usage=False)
    await task.refresh_from_db()
    assert task.status==4 and task.stage=='needs_review'


async def test_recursive_parent_cancellation_does_not_roll_back_when_child_is_already_stopped(monkeypatch):
    project,parent=await project_task(status=1,workflow_version='agent-skills-v1')
    child=await AiTask.create(task_type=2,status=1,request_params={'novel_id':project.id,'origin_run_id':str(parent.id),'workflow_version':'agent-skills-v1'})
    monkeypatch.setattr('services.creation_agent.production.finish_production_message',AsyncMock())
    await novel_controller.remove(project.id)
    await parent.refresh_from_db();await child.refresh_from_db()
    assert parent.status==child.status==5
    assert not await Novel.filter(id=project.id).exists()


async def test_cancellation_during_preparation_never_submits_the_analysis_model(monkeypatch):
    from models.config import AiModelConfig
    from services.project_analysis.handler import ProjectAnalysisTaskHandler
    project=await Novel.create(name='cancel-before-model',content='第一章 开始\n故事正文。')
    task=await AiTask.create(task_type=5,status=1,request_params={'novel_id':project.id})
    await AiModelConfig.create(name='preflight-text',task_type=5,model='mock',base_url='https://example.invalid',api_key='test',is_active=True)
    async def split_and_stop(project_id):
        await Chapter.create(novel_id=project_id,number=1,name='开始',content='故事正文。')
        await novel_controller.remove(project_id)
    request=AsyncMock()
    monkeypatch.setattr(novel_controller,'split',split_and_stop)
    monkeypatch.setattr('services.project_analysis.handler.create_json_completion',request)
    monkeypatch.setitem(ai_task_executor._handlers,AiTaskTypeEnum.project_analysis,ProjectAnalysisTaskHandler())
    await ai_task_executor.run(task)
    request.assert_not_awaited()
    assert sum(row.cost for row in await ModelUsageRecord.filter(novel_id=project.id))==0
    assert not await Novel.filter(id=project.id).exists()
