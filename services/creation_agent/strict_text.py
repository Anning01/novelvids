"""One JSON model request, with existing task events, receipts and accounting."""

import json
from uuid import UUID, uuid5

from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.exceptions import ModelHTTPError

from models.ai_task import AiTask
from models.creation_agent import AgentMessage
from models.novel import Novel
from prompts.text_tasks import render_text_task
from schemas.text_task_contracts import output_contract
from services.creation_agent.model_boundary import RecordedAgentModel
from services.creation_agent.operation_receipts import execute_step
from services.creation_agent.skill_execution import current_execution, require_agent, require_workflow_model, WORKFLOW_VERSION
from services.creation_agent.skill_stream import SkillRunActivity, skill_activity_label
from services.user_skills import snapshot_method
from utils.messages import localized_message


def require_text_execution(params):
    execution = current_execution.get()
    if execution is None or not params.get('output_contract'):
        raise ValueError(localized_message('旧版文本任务已停用，请重新发起生成；历史结果和用量记录仍保留。'))
    return execution


async def prepare_text_workflow(params: dict, task: str, skill_id: int | None = None) -> dict:
    chosen, limits = await require_agent(params.get('team_id'), params.get('assistant_model_config_id'), strict_output=True)
    from services.language import generation_language
    from services.creation_agent.submissions import submission
    parent = current_execution.get()
    inherited = {}
    if parent:
        inherited = {key: parent.params[key] for key in ('conversation_id', 'instruction_message_id', 'creation_run_id') if key in parent.params}
        inherited['origin_run_id'] = parent.params['task_id']
        if 'instruction_message_id' not in inherited:
            source = await AgentMessage.get_or_none(task_id=parent.params['task_id'], role='user')
            if source:
                inherited['instruction_message_id'] = source.id
        if task in {'assets', 'storyboard'}:
            inherited.update({key: parent.params[key] for key in ('creation_plan_id', 'creation_step_id') if key in parent.params})
    language = params.get('prompt_language') or await generation_language()
    rendering = {}
    if task in {'assets', 'storyboard'}:
        from models.chapter import Chapter
        from prompts.skill_pack import read_skill
        from services.creation_agent.plan_sources import fingerprint
        chapter = await Chapter.get(id=params['chapter_id'], novel_id=params['novel_id']).prefetch_related('novel')
        params = {**params, 'chapter_input_version': fingerprint([chapter.name, chapter.production_text, chapter.episode_pacing])}
        if task == 'assets':
            rendering = {'asset_specifications': json.loads(read_skill('asset_contract'))[language],
                         'aspect_ratio': chapter.novel.aspect_ratio or '16:9'}
    contract = output_contract(task, asset_specifications=rendering.get('asset_specifications'),
        duration_range=params.get('shot_duration_range', (1, 30)), blocking_maps=params.get('generate_blocking_maps', False))
    if rendering:
        contract['rendering'] = rendering
    return {**params, **(submission.get() or {}), **inherited,
            'workflow_version': WORKFLOW_VERSION, 'assistant_model_config_id': chosen.id,
            'agent_configuration': limits.model_dump(),
            'prompt_language': language,
            'creative_method': await snapshot_method(params.get('user_id') or 0, task, skill_id),
            'output_contract': contract}


async def verify_chapter_input(params):
    from services.story_memory.context import verify_bindings
    await verify_bindings(params)
    if 'chapter_input_version' not in params:
        return
    from models.chapter import Chapter
    from services.creation_agent.plan_sources import fingerprint
    chapter = await Chapter.get(id=params['chapter_id'], novel_id=params['novel_id'])
    if params['chapter_input_version'] != fingerprint([chapter.name, chapter.production_text, chapter.episode_pacing]):
        raise ValueError(localized_message('本集原文或剧本已修改，请刷新后查看'))


async def generate(execution, facts: dict) -> dict:
    from services.creation_agent.handler import configured_model
    from services.billing.recorder import record_ai_task_usage
    from services.creation_agent.skill_execution import user_instruction
    from schemas.creation_agent import AgentConfiguration

    params = execution.params
    chosen, _ = await require_workflow_model(params)
    limits = AgentConfiguration.model_validate(params['agent_configuration'])
    contract = params['output_contract']
    operation = contract['name']
    if operation == 'storyboard':
        from schemas.text_task_contracts import bind_storyboard_candidates
        contract = bind_storyboard_candidates(contract, facts['entities'])
        task = await AiTask.get(id=params['task_id'])
        task.request_params = {**task.request_params, 'output_contract': contract}
        await task.save(update_fields=['request_params'])
        params = {**params, 'output_contract': contract}
    key = f'model:strict:{operation}'
    project = await Novel.get(id=params['novel_id'])
    project_facts = {'name': project.name, 'setting': project.project_setting,
                     'style': project.custom_style_prompt or project.style_key}
    if operation in {'assets', 'storyboard'}:
        from prompts.skill_pack import read_skill
        from prompts.project_settings import audiovisual_guidance
        styles = json.loads(read_skill('styles'))
        style_kind = 'image' if operation == 'assets' else 'video'
        project_facts.update(aspect_ratio=project.aspect_ratio,
            style=(project.custom_style_prompt or styles.get(project.style_key, {}).get(style_kind, '')),
            audiovisual_guidance=audiovisual_guidance(project.audiovisual_guidance, execution.language))
        if operation == 'storyboard':
            project_facts['storyboard_strategy'] = json.loads(read_skill('strategies'))[params.get('storyboard_strategy') or project.storyboard_strategy or 'cinematic']
    instructions, content = render_text_task(language=execution.language,
        skill=params['creative_method'], context={
            'input': facts, 'user_request': await user_instruction(params),
            'project': project_facts})
    messages = [ModelRequest(parts=[SystemPromptPart(instructions), UserPromptPart(content)])]
    request = ModelRequestParameters()
    if operation in {'assets', 'storyboard', 'screenplay'}:
        from services.creation_agent.context_budget import wire_size
        from services.story_memory.context import MAX_GENERATION_MEMORY_CHARACTERS, generation_memory
        limit = limits.context_character_limit(chosen.max_context_characters)
        budget = MAX_GENERATION_MEMORY_CHARACTERS
        if limit is not None:
            available = limit - wire_size(messages, request)['total_characters'] - len(', "story_memory": ')
            budget = min(budget, available)
        memory = await generation_memory(execution, operation, budget)
        if memory is not None:
            payload = json.loads(content)
            payload['task_context']['input']['story_memory'] = memory
            messages[0].parts[1] = UserPromptPart(json.dumps(payload, ensure_ascii=False))

    child, _ = await AiTask.get_or_create(id=uuid5(UUID(params['task_id']), key), defaults={
        'task_type': 7, 'status': 2, 'request_params': {**params, 'parent_task_id': params['task_id'], 'model_config_id': chosen.id}})
    message, _ = await AgentMessage.get_or_create(task=child, role='assistant', defaults={
        'conversation_id': execution.message.conversation_id, 'request_id': child.id,
        'request_hash': str(child.id), 'run_input': {'internal_production_step': True},
        'model_snapshot': {'id': chosen.id, 'name': chosen.name, 'model': chosen.model, 'scope': chosen.scope, 'pricing': chosen.pricing}})
    model = configured_model(chosen, limits, output_contract=contract)
    model.strict_streaming = True
    activity = SkillRunActivity(message, params['task_id'])

    async def report(call):
        await activity.publish({'id': f'model:{child.id}:{call["index"]}', 'kind': 'status',
            'label': skill_activity_label(operation, execution.language),
            'status': 'running' if call['status'] == 'in_progress' else call['status'],
            'started_at': call['started_at'], 'finished_at': call.get('finished_at')})

    recorded = RecordedAgentModel(model, message=message, before_request=execution.before_request,
        max_characters=limits.context_character_limit(chosen.max_context_characters),
        limits=limits, on_activity=report, manage_context=False, stage=operation)
    rejected = False

    async def invoke():
        nonlocal rejected
        try:
            async with recorded.request_stream(messages, limits.output_model_settings(chosen.max_tokens), request) as stream:
                await activity(None, stream)
                response = stream.get()
        except ModelHTTPError as error:
            rejected = 400 <= error.status_code < 500 and error.status_code not in {408, 409}
            raise
        if response.finish_reason == 'content_filter':
            raise ValueError(localized_message('模型未完成本次请求，请调整内容后重试'))
        if response.finish_reason != 'stop':
            raise ValueError(localized_message('模型未完整返回结果，请调整输出上限或模型后重试'))
        # Decode JSON once; field instructions are supplied up front, without output validators or repairs.
        return json.loads(''.join(part.content for part in response.parts if isinstance(part, TextPart)))

    try:
        payload = await execute_step(params['task_id'], key, invoke, external=True,
            external_started=lambda: not rejected and any(call['status'] != 'completed' for call in recorded.calls))
        child.status, child.response_data = 3, payload
        await child.save(update_fields=['status', 'response_data'])
        return payload
    except BaseException:
        child.status = 4
        await child.save(update_fields=['status'])
        raise
    finally:
        try:
            await record_ai_task_usage(child, result=child.response_data)
        except Exception:
            await AiTask.filter(id=child.id).update(stage='billing_pending')
        finally:
            await model.client.close()
