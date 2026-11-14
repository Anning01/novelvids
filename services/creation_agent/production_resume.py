"""User-requested retries reuse successful steps without a manual review gate."""

from datetime import datetime, timezone
from uuid import uuid5

from fastapi import HTTPException
from tortoise.transactions import in_transaction
from tortoise.expressions import F

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.creation_agent import AgentConversation, AgentMessage
from services.creation_agent.run_recovery import project_revision
from utils.messages import localized_message


def supports_production_resume(task):
    return (task.task_type in {1, 2, 3, 5}
            and task.request_params.get('workflow_version') == 'agent-skills-v1'
            and not task.request_params.get('parent_task_id')
            and task.request_params.get('operation') in {None, 'assets', 'storyboard', 'screenplay', 'story', 'image', 'storyboard_sheet', 'project_cover'})


async def validate_resume_inputs(task, message, operations):
    from models.config import AiModelConfig
    from models.studio_call import StudioCall
    from services.creation_agent.step_context import validate_step_inputs

    checkpoint = await AgentOperation.get_or_none(task=task, key='recovery:inputs', state='completed')
    model = await AiModelConfig.get_or_none(id=checkpoint.result.get('model_id'), is_active=True) if checkpoint else None
    valid = bool(checkpoint and model)
    if valid and str(model.updated_at) != checkpoint.result.get('model_version'):
        # Catalog refreshes update timestamps without changing the selected model.
        snapshot = message.model_snapshot or {}
        child_ids = [uuid5(task.id, row.key) for row in operations if row.key.startswith('model:')]
        messages = await AgentMessage.filter(task_id__in=child_ids).values_list('id', flat=True)
        calls = StudioCall.filter(message_id__in=messages, model_config_id=model.id)
        valid = (snapshot.get('id') == model.id and snapshot.get('model') == model.model
                 and snapshot.get('pricing') == model.pricing and await calls.exists()
                 and not await calls.exclude(base_url=model.base_url.rstrip('/')).exists())
    if valid and await project_revision(task.request_params['novel_id']) != checkpoint.result.get('project_revision'):
        # Project bookkeeping also changes timestamps. Validate the frozen plan;
        # each model-input fingerprint still guards its exact input before reuse.
        valid = bool(task.request_params.get('creation_plan_id'))
        if valid:
            try:
                await validate_step_inputs(task.request_params)
            except ValueError:
                valid = False
    if not valid:
        raise HTTPException(409, localized_message('原文、设定或模型配置已变化，不能沿用旧断点。已完成结果仍保留。'))


async def resume_production(task_id, ctx):
    from auth.deps import require_roles
    from services.creation_agent.sessions import agent_sessions
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.event_log import agent_event_log
    from services.task_signals import task_signals

    conversation, message = await agent_sessions.for_task(task_id, ctx)
    await require_roles('admin', 'creator')(ctx)
    await agent_sessions.get(conversation.id, ctx)
    task = await AiTask.get(id=task_id)
    if not supports_production_resume(task):
        raise HTTPException(409, localized_message('当前任务不支持生产断点续跑，请从具体失败步骤继续。'))
    if task.status in {1, 2, 6}:
        return task
    if task.status not in {4, 5} or ai_task_executor.is_executing(task.id):
        raise HTTPException(409, localized_message('任务仍在收尾或已完成，请刷新后查看。'))
    operations = await AgentOperation.filter(task=task)
    retryable = []
    for operation in operations:
        if operation.state in {'running', 'uncertain', 'failed'}:
            retryable.append(operation.id)
    async with in_transaction():
        # Serialize admission with new chats and other resume clicks in this conversation.
        await AgentConversation.filter(id=conversation.id).update(updated_at=F('updated_at'))
        current = await AgentConversation.get(id=conversation.id)
        task = await AiTask.get(id=task_id)
        if task.status in {1, 2, 6}:
            return task
        if task.status not in {4, 5}:
            raise HTTPException(409, localized_message('任务仍在收尾或已完成，请刷新后查看。'))
        if current.active_task_id and current.active_task_id != task.id and await AiTask.filter(id=current.active_task_id, status__in=[1, 2, 6]).exists():
            raise HTTPException(409, localized_message('会话正在运行，请等待当前任务结束。'))
        if task.task_type != 2:
            await validate_resume_inputs(task, message, operations)
        for operation in operations:
            if operation.key.startswith('recovery:repair') and operation.state == 'completed':
                await AgentOperation.create(task=task,
                    key=f'resume:repair:{operation.id}:{task.request_params.get("resume_count", 0) + 1}',
                    state='completed', result=operation.result)
                await AgentOperation.filter(id=operation.id).update(state='pending', result={})
            if operation.id in retryable and operation.state == 'uncertain':
                await AgentOperation.create(task=task,
                    key=f'resume:retry:{operation.id}:{task.request_params.get("resume_count", 0) + 1}',
                    state='completed', result={'operation_key': operation.key, 'previous_state': operation.state,
                                              'policy': 'user_requested_retry_of_unfinished_step'})
        await AgentOperation.filter(id__in=retryable).update(state='pending')
        seq = await agent_event_log.start(message)
        await AgentMessage.filter(id=message.id).update(content='', run_input={**message.run_input, 'stream_start_seq': seq})
        await agent_event_log.append(message.id, [{'type': 'RUN_STARTED', 'runId': str(task.id),
            'threadId': str(conversation.id)}], seq)
        await AgentConversation.filter(id=conversation.id).update(active_task_id=task.id)
        await AiTask.filter(id=task.id).update(status=6, stage='resuming', error_message=None, finished_at=None,
            request_params={**task.request_params, 'resume_count': task.request_params.get('resume_count', 0) + 1},
            updated_at=datetime.now(timezone.utc))
    await task.refresh_from_db()
    await task_signals.publish(str(task.id))
    return task
