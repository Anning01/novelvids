"""Durable media jobs share receipts and recovery, but never own an Agent turn."""
from models.ai_task import AiTask
from services.creation_agent.skill_execution import current_execution, WORKFLOW_VERSION
from services.creation_agent.submissions import envelope
from utils.messages import localized_message


def is_media_task(params):
    return params.get('execution_mode') == 'media'


async def prepare_media_task(params):
    from services.language import generation_language
    params = envelope(dict(params))
    for key in ('api_key', 'base_url', 'assistant_model_config_id', 'agent_configuration',
                'skill_snapshot', 'conversation_id', 'origin_run_id', 'agent_runtime'):
        params.pop(key, None)
    parent = current_execution.get()
    if parent:
        params['prompt_language'] = parent.language
        for key in ('creation_plan_id', 'creation_step_id', 'creation_run_id', 'instruction_message_id'):
            if key in parent.params:
                params[key] = parent.params[key]
    target = await media_target(params)
    if target is not None:
        params['media_input_version'] = media_input_version(target)
    # Keep the durable receipt protocol so recovery and settlement stay compatible.
    params.update(workflow_version=WORKFLOW_VERSION, execution_mode='media')
    params.setdefault('prompt_language', await generation_language())
    return params


async def check_media_task(params):
    from services.creation_agent.handler import authorize_run
    from services.balance import ensure_solvent
    ctx = await authorize_run(params)
    if params.get('operation') in {'prepare_export', 'enhance_export'}:
        from services.video_enhancement.sources import require_generation_scope
        await require_generation_scope(params['novel_id'], ctx.team_id)
    await ensure_solvent(params.get('team_id'), params.get('user_id'))
    if not await AiTask.filter(id=params['task_id'], status=2).exists():
        raise ValueError(localized_message('任务已取消或结束'))


async def media_target(params):
    from models.asset import Asset
    from models.asset_variant import AssetVariant
    from models.scene import Scene
    if params.get('asset_id'):
        return await AssetVariant.get(id=params['variant_id']) if params.get('variant_id') else await Asset.get(id=params['asset_id'])
    if params.get('operation') == 'video':
        return await Scene.get(id=params['video_request']['scene_id'])
    return None


def media_input_version(target):
    from services.video_enhancement.media import digest
    return digest([getattr(target, 'base_traits', None), getattr(target, 'prompt', None),
                   getattr(target, 'prompt_params', None), getattr(target, 'description', None)])


async def media_input_matches(params):
    target = await media_target(params)
    return target is None or not params.get('media_input_version') or media_input_version(target) == params['media_input_version']


async def run_media_task(task, handler):
    from controllers.config import ai_model_config_controller
    from services.creation_agent.operation_receipts import execute_step
    params = {**task.request_params, 'task_id': str(task.id)}
    token = current_execution.set(None)
    try:
        await check_media_task(params)
        if not await media_input_matches(params):
            raise ValueError(localized_message('准备后的提示词已被修改，请重新确认生成'))
        target = await media_target(params)
        if target is not None:
            prompt = getattr(target, 'prompt', None) or getattr(target, 'base_traits', None)
            if not prompt and params.get('variant_id'):
                from models.asset import Asset
                prompt = (await Asset.get(id=params['asset_id'])).base_traits
            if not (prompt or '').strip():
                from fastapi import HTTPException
                raise HTTPException(422, localized_message('提示词不能为空'))
        if task.task_type == 2 and params.get('asset_id'):
            config = await ai_model_config_controller.get_active(2, params['model_config_id'], team_id=params.get('team_id'))
            params.update(base_url=config.base_url, api_key=config.api_key, model=config.model, api_protocol=config.api_protocol)
            return await execute_step(task.id, 'media:image', lambda: handler.execute(params), external=True)
        return await handler.execute(params)
    finally:
        current_execution.reset(token)


async def retry_media_task(task):
    from fastapi import HTTPException
    from models.agent_operation import AgentOperation
    from services.ai_task_executor import ai_task_executor
    from services.creation_agent.handler import authorize_run
    from services.creation_objects import project_write
    await authorize_run(task.request_params)
    async with project_write(task.request_params['novel_id']):
        await task.refresh_from_db()
        if task.status in {1, 2, 6}:
            return task
        if task.status not in {4, 5} or ai_task_executor.is_executing(task.id):
            raise HTTPException(409, localized_message('任务仍在收尾或已完成，请刷新后查看。'))
        attempt = task.request_params.get('resume_count', 0) + 1
        for row in await AgentOperation.filter(task=task, state__in=['running', 'uncertain', 'failed']):
            if row.state == 'uncertain':
                await AgentOperation.create(task=task, key=f'resume:retry:{row.id}:{attempt}', state='completed',
                    result={'operation_key': row.key, 'previous_state': row.state,
                            'policy': 'user_requested_retry_of_unfinished_step'})
            await AgentOperation.filter(id=row.id).update(state='pending')
        await AiTask.filter(id=task.id).update(status=6, stage='resuming', error_message=None, finished_at=None,
            request_params={**task.request_params, 'resume_count': attempt})
        await task.refresh_from_db()
        return task
