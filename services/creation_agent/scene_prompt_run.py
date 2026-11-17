"""Selected storyboard editing: one structured request, one atomic save."""

from models.creation_agent import AgentConversation, AgentMessage
from prompts.text_tasks import scene_prompt_batch_method
from schemas.creation_agent import AgentConfiguration
from schemas.text_task_contracts import scene_prompt_batch_contract
from services.creation_agent.authorization import direct_operation
from services.creation_agent.changes import CreationChanges
from services.creation_agent.event_log import agent_event_log
from services.creation_agent.skill_execution import SkillExecution
from services.creation_agent.skill_stream import skill_event_sink
from services.task_signals import task_signals
from services.user_skills import snapshot_method
from utils.messages import localized_message


def is_scene_prompt_run(request):
    return (request.write_scope == 'selected' and bool(request.targets)
            and all(target.kind == 'scene' for target in request.targets)
            and not request.production_intents and request.plan_confirmation is None
            and direct_operation(request.message) is None)


async def run_scene_prompt_edit(params, request, assistant, conversation, before_request):
    task_id = params['task_id']
    language = params.get('prompt_language', 'zh')
    limits = AgentConfiguration.model_validate(params['agent_configuration'])
    service = CreationChanges(novel_id=conversation.novel_id, task_id=task_id,
        request=request, max_batch_size=limits.max_targets, authorization_check=before_request)

    async def emit(*events):
        await agent_event_log.append(assistant.id, list(events), await agent_event_log.start(assistant))
        await task_signals.publish(task_id)

    await emit({'type': 'RUN_STARTED', 'runId': task_id, 'threadId': str(conversation.id)})
    token = skill_event_sink.set(emit)
    try:
        targets = await service.read(request.targets, full_prompt=True)
        method = await snapshot_method(params.get('user_id') or 0, 'storyboard')
        execution = SkillExecution({**params,
            'creative_method': scene_prompt_batch_method(method),
            'output_contract': scene_prompt_batch_contract(target.id for target in request.targets)},
            assistant, before_request)
        turns = await AgentMessage.filter(conversation_id=conversation.id, role='user', id__lt=assistant.id).exclude(
            task_id=task_id).order_by('-id').limit(limits.history_runs).values_list('task_id', flat=True)
        history = await AgentMessage.filter(conversation_id=conversation.id, task_id__in=turns).order_by('id').values('role', 'content')
        output = await execution.generate_strict({'targets': targets,
            'user_request': request.message, 'conversation_summary': conversation.summary,
            'history': history})
        prompts = {target.id: output['prompts'][str(target.id)] for target in request.targets
                   if output['prompts'][str(target.id)] is not None}
        change = await service.save_scene_prompts(prompts, 'scene-prompt-edit') if prompts else None
        saved = localized_message('分镜提示词已修改并保存。', _language=language) if change else ''
        assistant.content = '\n'.join(text for text in (saved, output['reply']) if text)
        await assistant.save(update_fields=['content'])
        message_id = f'{task_id}:reply'
        await emit(
            {'type': 'TEXT_MESSAGE_START', 'messageId': message_id, 'role': 'assistant'},
            {'type': 'TEXT_MESSAGE_CONTENT', 'messageId': message_id, 'delta': assistant.content},
            {'type': 'TEXT_MESSAGE_END', 'messageId': message_id},
            {'type': 'RUN_FINISHED', 'runId': task_id, 'threadId': str(conversation.id)},
        )
        return {'conversation_id': conversation.id, 'change_ids': [change.id] if change else []}
    except Exception as error:
        # No tool loop, ModelRetry, fallback model, or repair request on this path.
        await emit({'type': 'RUN_ERROR', 'message': str(error)})
        raise
    finally:
        skill_event_sink.reset(token)
        await AgentConversation.filter(id=conversation.id, active_task_id=task_id).update(active_task_id=None)
