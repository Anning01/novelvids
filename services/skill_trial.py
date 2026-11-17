"""A single, read-only skill trial using the production text contract and accounting."""

import asyncio
from copy import copy
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from types import SimpleNamespace

import anyio
from ag_ui.core import RunAgentInput
from fastapi import HTTPException
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.ui.ag_ui import AGUIEventStream

from models.ai_task import AiTask
from prompts.skill_pack import read_skill
from prompts.text_tasks import render_text_task
from schemas.creation_agent import AgentConfiguration
from schemas.text_task_contracts import output_contract
from schemas.user_skill import SkillTrialInput
from services.balance import ensure_solvent
from services.billing.platform import active_model_call, finish_model_call
from services.billing.recorder import billing_recorder, _consume_team_balance
from services.creation_agent.handler import configured_model
from services.language import generation_language
from services.model_concurrency import model_slots
from services.model_resolution import resolve_scope_configs
from utils.enums import AiTaskTypeEnum
from utils.messages import localized_message

logger = logging.getLogger(__name__)


async def prepare_trial(body: SkillTrialInput, ctx):
    configs = await resolve_scope_configs(AiTaskTypeEnum.creation_agent.value, ctx.team_id,
        capability_filter=lambda row: row.supports_json_output)
    chosen = next((row for row in configs if row.id == body.model_config_id), None)
    if chosen is None:
        raise HTTPException(400, localized_message('所选模型不可用，请重新选择'))
    chosen = copy(chosen)
    for field in ('thinking', 'reasoning_effort'):
        if getattr(body, field) is not None:
            setattr(chosen, field, getattr(body, field) or None)
    language = await generation_language()
    specifications = json.loads(read_skill('asset_contract'))[language] if body.skill.task == 'assets' else None
    schema = output_contract(body.skill.task, asset_specifications=specifications)['schema']
    instructions, content = render_text_task(language=language, skill=body.skill.model_dump(),
        context={'input': body.input}, output_schema=schema)
    if chosen.max_context_characters and len(instructions) + len(content) > chosen.max_context_characters:
        raise HTTPException(400, localized_message('内容超过模型上下文上限，请缩短技能或测试输入'))
    await ensure_solvent(ctx.team_id, ctx.user.id if ctx.user else None)
    return chosen, instructions, content


async def stream_trial(body, ctx, prepared):
    chosen, instructions, content = prepared
    user_id = ctx.user.id if ctx.user else None
    # Standalone calls use the existing zero project attribution, never a real project.
    task = await AiTask.create(task_type=AiTaskTypeEnum.prompt_optimization.value, status=2,
        started_at=datetime.now(timezone.utc), request_params={'operation': 'skill_trial',
            'skill_task': body.skill.task, 'novel_id': 0, 'team_id': ctx.team_id, 'user_id': user_id, 'model_config_id': chosen.id})
    model = configured_model(chosen, AgentConfiguration())
    protocol = AGUIEventStream(run_input=RunAgentInput(thread_id=str(task.id), run_id=str(task.id),
        messages=[], tools=[], context=[], state={}, forwarded_props={}))
    call = {}
    stream = None
    output = ''
    usage = {}
    completed = False

    def event(kind, **payload):
        return 'data: ' + json.dumps({'type': kind, **payload}, ensure_ascii=False) + '\n\n'

    try:
        yield event('status', status='waiting')
        async with model_slots.hold(chosen.id):
            await ensure_solvent(ctx.team_id, user_id)
            token = active_model_call.set((SimpleNamespace(task_id=task.id, id=None), call))
            try:
                yield event('status', status='running')
                messages = [ModelRequest(parts=[SystemPromptPart(instructions), UserPromptPart(content)])]
                async with model.request_stream(messages, None, ModelRequestParameters()) as stream:
                    async for item in stream:
                        async for public in protocol.handle_event(item):
                            if public.type == 'TEXT_MESSAGE_CONTENT':
                                output += public.delta
                                yield event('output', delta=public.delta)
                            elif public.type == 'THINKING_TEXT_MESSAGE_CONTENT':
                                yield event('thinking', delta=public.delta)
                if stream.finish_reason != 'stop':
                    raise ValueError('incomplete_response')
                json.loads(output)
                completed = True
            finally:
                active_model_call.reset(token)
    except asyncio.CancelledError:
        task.status = 5
        raise
    except Exception as error:
        logger.warning('Skill trial failed task_id=%s error_type=%s', task.id, type(error).__name__)
        yield event('error', message=localized_message('试运行未完成，请检查模型设置或缩短输入后重试'))
    finally:
        # Disconnects stop inference but must still preserve the reported usage.
        with anyio.CancelScope(shield=True):
            task.status = 3 if completed else task.status if task.status == 5 else 4
            task.finished_at = datetime.now(timezone.utc)
            if stream is not None:
                usage = asdict(stream.usage())
                usage['cache_usage_reported'] = bool(usage.get('cache_read_tokens') or usage.get('details', {}).get('cache_usage_reported'))
            duration = (task.finished_at - task.started_at).total_seconds()
            task.response_data = {'output': output, 'usage': usage}
            await task.save(update_fields=['status', 'finished_at', 'response_data'])
            try:
                await finish_model_call(call, completed=completed, usage=usage, duration=duration)
                record = await billing_recorder.record_text(novel_id=0, task_type=task.task_type,
                    config_snapshot=chosen, token_usage=usage, status=task.status, duration_seconds=duration,
                    ai_task_id=task.id, team_id=ctx.team_id, user_id=user_id)
                if record is None:
                    raise RuntimeError('Skill trial usage recording failed')
                await _consume_team_balance(record, ctx.team_id, user_id=user_id)
            finally:
                await model.client.close()
    if completed:
        yield event('done', usage=usage)
