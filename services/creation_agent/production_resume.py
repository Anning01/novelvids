"""Reuse successful steps; retry lost results only after their requests finish."""

from datetime import datetime, timezone
from uuid import uuid5

import httpx
from fastapi import HTTPException
from tortoise.transactions import in_transaction
from tortoise.expressions import F

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.creation_agent import AgentConversation, AgentMessage
from services.creation_agent.run_recovery import project_revision
from utils.messages import localized_message


def supports_production_resume(task):
    return (task.task_type in {1, 3, 5}
            and task.request_params.get('workflow_version') == 'agent-skills-v1'
            and not task.request_params.get('parent_task_id')
            and task.request_params.get('operation') in {None, 'assets', 'storyboard', 'screenplay', 'story'})


async def check_external_step(task, operation):
    from models.config import AiModelConfig
    from models.studio_call import StudioCall
    from schemas.platform_billing import PlatformReceiptOut

    child = await AgentMessage.get_or_none(task_id=uuid5(task.id, operation.key), role='assistant')
    calls = (child.usage or {}).get('calls', []) if child else []
    unresolved = [call for call in calls if call.get('status') != 'completed']
    if not unresolved:
        raise HTTPException(409, localized_message('外部请求结果待核对，不能重复生成。已完成步骤仍保留。'))
    for call in unresolved:
        row = await StudioCall.get_or_none(id=call.get('studio_call_id'), message_id=child.id)
        config = await AiModelConfig.get_or_none(id=row.model_config_id) if row else None
        if not row or not config or config.base_url.rstrip('/') != row.base_url:
            raise HTTPException(409, localized_message('外部请求结果待核对，不能重复生成。已完成步骤仍保留。'))
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
                response = await client.get(row.base_url + (f'/requests/{row.platform_request_id}' if row.platform_request_id else '/requests'),
                    params=None if row.platform_request_id else {'request_key': str(row.request_key)},
                    headers={'Authorization': 'Bearer ' + config.api_key})
                response.raise_for_status()
                receipt = PlatformReceiptOut.model_validate(response.json())
                if row.platform_request_id and receipt.id != row.platform_request_id:
                    raise ValueError('Receipt does not match the original request')
        except (httpx.HTTPError, ValueError):
            raise HTTPException(409, localized_message('暂时无法核对平台回执，未发起任何生成，请稍后再试。')) from None
        if receipt.status == 'completed' and receipt.settlement.status == 'settled':
            continue
        if receipt.status != 'rejected' or receipt.settlement.status != 'not_charged':
            raise HTTPException(409, localized_message('外部请求仍在处理或结算待核对，未发起新的生成。'))


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
        if operation.state in {'running', 'uncertain'}:
            if not operation.key.startswith('model:'):
                raise HTTPException(409, localized_message('外部请求结果待核对，不能重复生成。已完成步骤仍保留。'))
            await check_external_step(task, operation)
            retryable.append(operation.id)
        elif operation.state == 'failed' and operation.key.startswith('model:'):
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
        await validate_resume_inputs(task, message, operations)
        for operation in operations:
            if operation.id in retryable and operation.state == 'uncertain':
                await AgentOperation.create(task=task,
                    key=f'resume:retry:{operation.id}:{task.request_params.get("resume_count", 0) + 1}',
                    state='completed', result={'operation_key': operation.key, 'previous_state': operation.state,
                                              'policy': 'retry_confirmed_finished_request_with_missing_result'})
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
