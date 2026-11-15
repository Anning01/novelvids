"""Resume text planning from immutable receipts, without replaying production."""

from fastapi import HTTPException

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.creation_agent import AgentMessage, PromptChange, CreationConstraint
from models.chapter import Chapter
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.scene import Scene
from models.novel import Novel
from schemas.creation_agent import AgentRunRequest
from services.creation_agent.plan_sources import fingerprint
from services.creation_agent.authorization import public_run_input
from services.creation_agent.reliability import recovery_root


async def project_revision(novel_id):
    # JSON-only checkpoints work on SQLite and PostgreSQL; no schema migration.
    values = []
    for model, filters in ((Novel, {'id': novel_id}), (Chapter, {'novel_id': novel_id}),
            (Asset, {'novel_id': novel_id}), (AssetVariant, {'asset__novel_id': novel_id}),
            (Scene, {'chapter__novel_id': novel_id}), (CreationConstraint, {'novel_id': novel_id})):
        values.append(await model.filter(**filters).order_by('id').values('id', 'updated_at'))
    return fingerprint(values)


async def checkpoint_inputs(params):
    from models.config import AiModelConfig
    root = await recovery_root(params)
    if await AgentOperation.filter(task_id=root, key='recovery:inputs', state='completed').exists():
        return
    model = await AiModelConfig.get_or_none(id=params.get('assistant_model_config_id') or params.get('model_config_id'))
    await AgentOperation.update_or_create(task_id=root, key='recovery:inputs', defaults={
        'state': 'completed', 'result': {'project_revision': await project_revision(params['novel_id']),
            'model_id': model.id if model else None, 'model_version': str(model.updated_at) if model else None}})


async def resume_source(conversation, task_id):
    source = await AgentMessage.get_or_none(task_id=task_id, conversation_id=conversation.id, role='user')
    if source is None:
        raise HTTPException(404, '当前会话不存在该任务')
    task = await AiTask.get(id=task_id)
    root = await recovery_root({'task_id': str(task.id)})
    if task.status != 4 or task.request_params.get('operation') or source.run_input.get('targets') or source.run_input.get('write_scope') not in {'chapter', 'project'}:
        raise HTTPException(409, '当前任务不能沿用规划步骤，请重新提交生成要求')
    if task.request_params.get('has_creation_plan') or await PromptChange.filter(task=task).exists() or await AgentOperation.filter(task=task, key__startswith='submit:').exists():
        raise HTTPException(409, '此任务已有生产或保存记录，请从具体失败步骤继续')
    if await AgentOperation.filter(task_id=root, key='recovery:repair', state='completed').exists():
        raise HTTPException(409, '本次任务的修复额度已用完，请调整要求后发起新任务')
    rows = await AgentOperation.filter(task=task)
    failure = await AgentOperation.get_or_none(task_id=root, key='recovery:failure')
    if failure and any(issue.get('code') == 'output_length' for issue in failure.result.get('issues', [])):
        raise HTTPException(409, '输出额度不足，请调整输出设置或模型后发起新任务')
    checkpoint = await AgentOperation.get_or_none(task_id=root, key='recovery:inputs', state='completed')
    if checkpoint is None or checkpoint.result['project_revision'] != await project_revision(conversation.novel_id):
        raise HTTPException(409, '原文、对象或约束已有变化，请重新规划')
    from models.config import AiModelConfig
    model = await AiModelConfig.get_or_none(id=checkpoint.result.get('model_id'), is_active=True)
    if model is None or str(model.updated_at) != checkpoint.result.get('model_version'):
        raise HTTPException(409, '原模型配置已有变化，请重新规划')
    request = AgentRunRequest.model_validate(public_run_input(source.run_input))
    return task, source, request, rows, root


async def copy_planning_receipts(source_rows, task):
    for row in source_rows:
        if row.state in {'failed', 'uncertain', 'running'} and row.key.startswith('model:'):
            await AgentOperation.create(task=task, key=row.key, state='pending', external=row.external,
                result={'recovered_failure': True})
            continue
        if row.state != 'completed' or not row.key.startswith(('model:', 'model-input:', 'candidate:')):
            continue
        await AgentOperation.create(task=task, key=row.key, state='completed', external=row.external, result=row.result)
