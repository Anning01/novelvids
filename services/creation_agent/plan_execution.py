"""Resume a confirmed dependency plan without replaying completed submissions."""

from uuid import UUID, uuid5

from models.agent_operation import AgentOperation
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.creation_agent import AgentMessage
from models.scene import Scene
from models.video import Video
from schemas.agent_workflow import ProductionIntent
from schemas.creation_agent import AgentRunRequest
from services.creation_agent.intent_tools import submit_intent
from services.creation_agent.plans import load_plan
from services.creation_agent.plan_sources import plan_activity
from services.creation_agent.skill_execution import SkillExecution, current_execution
from services.creation_agent.step_context import validate_step_inputs
from services.creation_agent.waiting import WaitingForDependencies
from utils.messages import localized_message


async def targets_for_step(step, records):
    if step.target_id:
        return [step.target_id]
    upstream = records[step.source_step].result
    return upstream.get('asset_ids' if step.operation == 'image' else 'scene_ids', [])


async def existing_result(step, target_id):
    if step.mode != 'fill_missing':
        return None
    if step.operation == 'storyboard':
        scenes = await Scene.filter(chapter_id=target_id).order_by('sequence')
        if scenes:
            return {'scene_ids': [row.id for row in scenes]}
    if step.operation == 'image':
        target = await AssetVariant.get(id=step.variant_id) if step.variant_id else await Asset.get(id=target_id)
        images = target.images if step.variant_id else ([target.main_image] if target.main_image else [])
        if images:
            return {'asset_ids': [target_id], 'images': images}
    if step.operation == 'video':
        video = await Video.filter(scene_id=target_id, status=3).order_by('-id').first()
        if video and video.url:
            return {'video_id': video.id, 'url': video.url}
    return None


class CreationPlanRunner:
    def __init__(self, execution):
        self.execution = execution
        self.params = execution.params

    async def run(self):
        plan = await load_plan(self.params['creation_plan_id'], novel_id=self.params['novel_id'])
        records = {row.key.removeprefix('plan-step:'): row for row in await AgentOperation.filter(
            task_id=self.params['task_id'], key__startswith='plan-step:')}
        for step in plan.steps:
            await self.execution.before_request()
            if step.id in records and records[step.id].state == 'completed':
                continue
            if any(records.get(key) and records[key].result.get('status') in {'failed', 'blocked'} for key in step.depends_on):
                records[step.id] = await self.finish(step, {'status': 'blocked', 'error': localized_message('前置步骤未完成')})
                continue
            if any(key not in records or records[key].state != 'completed' for key in step.depends_on):
                continue
            identifiers = await targets_for_step(step, records)
            children, outputs, errors = [], [], []
            active = False
            params = {**self.params, 'creation_step_id': step.id}
            step_execution = SkillExecution(params, self.execution.message, self.execution.before_request)
            token = current_execution.set(step_execution)
            try:
                if not identifiers:
                    raise ValueError(localized_message('前置步骤未产生可生成对象'))
                for target_id in identifiers:
                    outcome = await self.target(step_execution, step, target_id)
                    if outcome.get('error'):
                        errors.append(outcome['error'])
                        continue
                    if 'kept' in outcome:
                        outputs.append(outcome['kept'])
                        continue
                    task = await AiTask.get(id=outcome['task_id'])
                    children.append(str(task.id))
                    if task.status == 3:
                        output = task.response_data or {}
                        if step.operation == 'image':
                            output = {**output, 'asset_ids': [target_id]}
                        outputs.append(output)
                        if (task.response_data or {}).get('not_applied_reason'):
                            errors.append(task.response_data['not_applied_reason'])
                    elif task.status in {4, 5}:
                        errors.append(task.error_message or localized_message('生成未完成'))
                    else:
                        active = True
                if active:
                    continue
                if errors:
                    records[step.id] = await self.finish(step, {'status': 'failed', 'error': '；'.join(errors), 'task_ids': children, 'outputs': outputs})
                elif len(outputs) == len(identifiers):
                    merged = {'status': 'completed' if children else 'skipped', 'task_ids': children, 'outputs': outputs,
                        'asset_ids': sorted({i for item in outputs for i in item.get('asset_ids', [])}),
                        'scene_ids': sorted({i for item in outputs for i in item.get('scene_ids', [])})}
                    records[step.id] = await self.finish(step, merged)
            except Exception as error:
                # Cancellation still propagates (CancelledError is a BaseException).
                records[step.id] = await self.finish(step, {'status': 'failed', 'error': str(error)})
            finally:
                current_execution.reset(token)
        if any(step.id not in records or records[step.id].state != 'completed' for step in plan.steps):
            raise WaitingForDependencies()
        results = [{'label': step.label, **records[step.id].result} for step in plan.steps]
        failed = [item for item in results if item['status'] in {'failed', 'blocked'}]
        content = localized_message('创作任务已完成') if not failed else localized_message('部分步骤未完成，已保留成功结果')
        content += '\n' + '\n'.join(f"{item['label']}：{item.get('error') or localized_message('已保留已有成果' if item['status'] == 'skipped' else '已完成')}" for item in results)
        await AgentMessage.filter(id=self.execution.message.id).update(content=content)
        return {'steps': results, 'partial': bool(failed)}

    async def target(self, execution, step, target_id):
        await self.execution.before_request()
        if step.operation in {'image', 'video'}:
            target_params = {'asset_id': target_id} if step.operation == 'image' else {'video_request': {'scene_id': target_id}}
            execution = SkillExecution({**execution.params, **target_params}, execution.message, execution.before_request)
        key = f'plan-target:{step.id}:{target_id}'
        outcome = await AgentOperation.get_or_none(task_id=self.params['task_id'], key=key, state='completed')
        if outcome:
            return outcome.result
        request_id = uuid5(UUID(self.params['task_id']), f'{step.id}:{target_id}')
        receipt = await AgentOperation.get_or_none(task_id=self.params['task_id'], key='submit:' + str(request_id), state='completed')
        if receipt:
            return receipt.result
        try:
            await validate_step_inputs(execution.params)
            kept = await existing_result(step, target_id)
            if kept is not None:
                from services.creation_agent.creative_checks import check_preserved_result
                await check_preserved_result(execution, step, target_id, kept)
                result = {'kept': kept}
            else:
                # Targets are resolved exclusively from the confirmed snapshot
                # or an approved predecessor's actual saved output.
                intent = ProductionIntent(operation=step.operation, target_id=target_id, variant_id=step.variant_id,
                    replace_existing=step.operation == 'storyboard' and step.mode == 'revise', request_id=request_id)
                request = AgentRunRequest(request_id=request_id, message=localized_message('执行已确认创作步骤'),
                    write_scope='project', production_intents=[intent])
                result = await submit_intent(intent, request=request, novel_id=self.params['novel_id'])
                await plan_activity(self.execution, f'step:{step.id}', step.label, status='running')
        except Exception as error:
            result = {'error': str(error)}
        await AgentOperation.create(task_id=self.params['task_id'], key=key, state='completed', result=result)
        return result

    async def finish(self, step, result):
        if result.get('status') in {'completed', 'skipped'}:
            from services.creation_agent.object_state import object_version
            versions = {}
            for identifier in result.get('asset_ids', []):
                target = await Asset.get(id=identifier)
                versions[f'asset:{identifier}'] = await object_version(target)
            for identifier in result.get('scene_ids', []):
                target = await Scene.get(id=identifier)
                versions[f'scene:{identifier}'] = await object_version(target)
            if step.variant_id:
                target = await AssetVariant.get(id=step.variant_id)
                versions[f'variant:{target.id}'] = await object_version(target)
            result['object_versions'] = versions
        row, _ = await AgentOperation.update_or_create(task_id=self.params['task_id'], key=f'plan-step:{step.id}',
            defaults={'state': 'completed', 'result': result})
        await plan_activity(self.execution, f'step:{step.id}', step.label,
            status='failed' if result['status'] in {'failed', 'blocked'} else 'completed',
            detail=result.get('error', localized_message('已保留已有成果') if result['status'] == 'skipped' else ''))
        return row


async def run_confirmed_plan(params, assistant):
    from services.creation_agent.handler import authorize_run
    from services.creation_agent.sessions import agent_configuration

    async def before_request():
        await authorize_run(params)
        if not (await agent_configuration()).enabled or not await AiTask.filter(id=params['task_id'], status=2).exists():
            raise ValueError(localized_message('任务已停止，不能继续执行'))
    execution = SkillExecution(params, assistant, before_request)
    from services.creation_agent.event_log import agent_event_log
    if await agent_event_log.last(assistant) is None:
        await agent_event_log.append(assistant.id, [{'type': 'RUN_STARTED', 'runId': params['task_id'],
            'threadId': str(assistant.conversation_id)}], 0)
    token = current_execution.set(execution)
    try:
        return await CreationPlanRunner(execution).run()
    finally:
        current_execution.reset(token)
