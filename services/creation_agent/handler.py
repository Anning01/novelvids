"""Run a private creation conversation inside the existing AI task executor."""

from services.creation_agent.authorization import public_run_input
from utils.messages import localized_message

import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from openai import AsyncOpenAI
from starlette.requests import Request
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits
from ag_ui.core import TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent

from auth.deps import AuthContext, get_auth_context, ensure_novel_access, require_roles
from config import settings
from models.ai_task import AiTask
from models.chapter import Chapter
from models.creation_agent import AgentConversation, AgentMessage, PromptChange
from models.novel import Novel
from schemas.creation_agent import AgentConfiguration, AgentRunRequest, CreationReply
from services.ai_task_executor import BaseTaskHandler
from services.creation_agent.model_boundary import RecordedAgentModel
from services.creation_agent.model_usage import UsagePreservingChatModel
from services.creation_agent.runtime import CreationAgentDeps, stream_creation_agent
from services.creation_agent.sessions import agent_models
from services.creation_agent.tools import PromptEditService
from services.creation_agent.changes import CreationChanges
from services.creation_agent.context import chapter_context
from services.creation_agent.memory import creation_memory
from services.creation_agent.history import prepare_history
from services.creation_agent.event_log import agent_event_log
from services.task_signals import task_signals
from utils.enums import TaskStatusEnum, UserStatusEnum


async def authorize_run(params: dict) -> AuthContext:
    ctx = AuthContext()
    if settings.AUTH_ENABLED:
        from auth.models import User
        user = await User.get_or_none(id=params.get("user_id"), status=UserStatusEnum.active.value)
        if user is None:
            raise HTTPException(403, localized_message('运行用户已不可用'))
        headers = [(b"x-team-id", str(params["team_id"]).encode())] if params.get("team_id") else []
        ctx = await get_auth_context(Request({"type": "http", "headers": headers}), user=user)
    await require_roles("admin", "creator")(ctx)
    await ensure_novel_access(params["novel_id"], ctx)
    return ctx


def configured_model(config, limits: AgentConfiguration, *, structured_output=True):
    from services.billing.platform import is_platform_model, platform_text_client
    client_options = {"http_client": platform_text_client(config)} if is_platform_model(config) else {}
    client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key,
                         max_retries=0, timeout=None, **client_options)
    extra_body = {}
    if structured_output and getattr(config, 'supports_json_output', False):
        extra_body['response_format'] = {'type': 'json_object'}
    if getattr(config, 'thinking', None) in ('enabled', 'disabled'):
        extra_body['thinking'] = {'type': config.thinking}
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    provider = OpenAIProvider(openai_client=client)
    # Reasoning endpoints can reject tool_choice=required; output validation stays in the Agent.
    profile = OpenAIModelProfile.from_profile(provider.model_profile(config.model)).update(
        OpenAIModelProfile(openai_supports_tool_choice_required=False)
    )
    return UsagePreservingChatModel(config.model, provider=provider, profile=profile,
                                   settings={'extra_body': extra_body})


def public_run_error(message: str, calls: list[dict], *, turn_limited: bool = False) -> str:
    """Return actionable fixed copy without disclosing a provider's error payload."""
    if any(call.get("platform_balance_insufficient") for call in calls):
        return localized_message("API 平台账户可用额度不足，请前往 API 平台检查余额和限额")
    if turn_limited and ('Unknown tool name' in message or 'Exceeded maximum retries' in message):
        message = '本轮模型调用次数已达到配置上限'
    if any(marker in message for marker in ('上下文超过配置上限', 'Context exceeds the limit', 'Context limit exceeded')):
        if calls:
            return localized_message('本轮多次校验重试后超过了上下文额度。已保存的修改仍然有效，请编辑要求后重试。')
        return localized_message('当前内容超过助手的上下文额度。请减少选中的对象，或在助手设置提高上下文额度后重试。')
    if '本轮模型调用次数已达到配置上限' in message or localized_message('本轮模型调用次数已达到配置上限') in message or 'request_limit' in message:
        return localized_message('本轮处理次数已达到上限。已保存的修改可在记录中查看，请继续描述尚未完成的调整。')
    if '本轮 token 消耗已达到配置上限' in message or localized_message('本轮 token 消耗已达到配置上限') in message or 'total_tokens_limit' in message:
        return localized_message('本轮用量已达到上限。已保存的修改可在记录中查看，请继续描述尚未完成的调整。')
    if 'Context remains above the input budget' in message:
        return localized_message('当前工作上下文压缩后仍超过设置额度。请提高工作上下文额度，或减少本轮输入；已保存的修改仍然有效。')
    last_finish = next((call['finish_reason'] for call in reversed(calls) if call.get('finish_reason') and call.get('phase', 'main') != 'summary'), None)
    if last_finish == 'length':
        return localized_message('模型本次输出达到上限，未能完成要求。请在助手设置提高单次输出上限，或切换模型后重试。')
    if '增量修复已用完' in message or 'incremental repair' in message:
        return localized_message('本次任务的增量修复已用完，候选和调用记录已保留，请核对失败步骤。')
    if any(marker in message.lower() for marker in ('exceeded maximum retries', 'exceeded max retries count')):
        return localized_message('模型连续提交的内容未通过工具或输出校验，本轮已停止。请缩小修改范围后重试；已保存的修改可在记录中查看。')
    return localized_message('创作助手执行失败。请查看已保存的修改，确认模型可用后重试。')


class CreationAgentTaskHandler(BaseTaskHandler):
    async def execute(self, request_params: dict) -> dict:
        task_id = request_params["task_id"]
        user_message = await AgentMessage.get(task_id=task_id, role="user")
        assistant = await AgentMessage.get(task_id=task_id, role="assistant")
        if request_params.get('operation') == 'creation_plan':
            from services.creation_agent.plan_execution import run_confirmed_plan
            return await run_confirmed_plan(request_params, assistant)
        conversation = await AgentConversation.get(id=assistant.conversation_id)
        request = AgentRunRequest.model_validate(public_run_input(user_message.run_input))
        limits = AgentConfiguration.model_validate(request_params["agent_configuration"])

        async def before_request():
            ctx = await authorize_run(request_params)
            if not await AiTask.filter(id=task_id, status=TaskStatusEnum.running.value).exists():
                raise ValueError(localized_message('运行已停止，不能继续请求模型或写入'))
            chosen = next((config for config in await agent_models(ctx) if config.id == request_params["model_config_id"]), None)
            if chosen is None:
                raise ValueError(localized_message('运行模型已停用或不可访问，请重新选择模型'))
            return chosen

        chosen = await before_request()
        service = PromptEditService(novel_id=conversation.novel_id, task_id=assistant.task_id,
            allowed_targets={(target.kind, target.id) for target in request.targets},
            max_batch_size=limits.max_targets, authorization_check=before_request)
        novel = await Novel.get(id=conversation.novel_id)
        chapter = await Chapter.get_or_none(id=request.chapter_id, novel_id=novel.id) if request.chapter_id else None
        progressive = 'write_scope' in user_message.run_input
        context = {"project": {"id": novel.id, "name": novel.name, "outline": novel.story_outline,
                              "setting": novel.project_setting, "style": novel.custom_style_prompt or novel.style_key},
                   "chapter": chapter_context(chapter, max(500, limits.max_context_characters // 3) if limits.max_context_characters is not None else limits.context_page_characters),
                   "conversation_summary": conversation.summary}
        if progressive:
            context['project'] = {'id': novel.id, 'name': novel.name, 'style': novel.custom_style_prompt or novel.style_key}
            context['chapter'] = {'id': chapter.id, 'name': chapter.name, 'number': chapter.number} if chapter else None
        context['constraints'] = await creation_memory.applicable(novel.id, request)
        async def refresh_context(chapter_offset: int | None = None):
            await before_request()
            await novel.refresh_from_db()
            current_chapter = await Chapter.get_or_none(id=request.chapter_id, novel_id=novel.id) if request.chapter_id else None
            context['chapter'] = (chapter_context(current_chapter, limits.context_page_characters, chapter_offset)
                if not progressive or chapter_offset is not None else
                {'id': current_chapter.id, 'name': current_chapter.name, 'number': current_chapter.number} if current_chapter else None)
            if not progressive:
                context['project'].update(outline=novel.story_outline, setting=novel.project_setting,
                                          style=novel.custom_style_prompt or novel.style_key)
            context['constraints'] = await creation_memory.applicable(novel.id, request)
            return context

        async def check_context():
            if await creation_memory.applicable(novel.id, request) != context['constraints']:
                raise ValueError(localized_message('适用的创作约束已被更新，请重新读取上下文后再修改'))
            return context['constraints']

        service.context_check = check_context
        changes = CreationChanges(novel_id=novel.id, task_id=assistant.task_id, request=request,
                                  max_batch_size=limits.max_targets, authorization_check=before_request,
                                  max_context_characters=limits.max_context_characters)
        changes.chapter_character_budget = limits.context_page_characters
        if progressive:
            context.update(await changes.prepare_context())
        from services.creation_agent.run_recovery import checkpoint_inputs
        await checkpoint_inputs(request_params)
        deep = request_params.get("agent_runtime") == "deepagents"
        model = configured_model(chosen, limits, structured_output=False) if deep else configured_model(chosen, limits)
        from services.creation_agent.reliability import recovery_root
        recorded_model = RecordedAgentModel(model, message=assistant, before_request=before_request,
            max_characters=limits.context_character_limit(chosen.max_context_characters),
            request_limit=limits.request_limit, total_tokens_limit=limits.total_tokens_limit, limits=limits,
            repair_root=await recovery_root(request_params), manage_context=not deep)
        flush_lock = asyncio.Lock()
        buffer = []
        content = ""
        last_flush = time.monotonic()
        error = ''
        next_seq = await agent_event_log.start(assistant)
        async def notify_compaction():
            if deep:
                deps.read_cache.clear()
            buffer.append({'type': 'CUSTOM', 'name': 'context_compaction', 'value': {'status': 'running'}})
            await flush()
        recorded_model.budget.on_compact = notify_compaction
        final_message_id = f'{task_id}:validated-reply'

        async def flush():
            nonlocal last_flush, next_seq
            async with flush_lock:
                pending = list(buffer)
                buffer.clear()
                if pending:
                    next_seq = await agent_event_log.append(assistant.id, pending, next_seq)
                await AgentMessage.filter(id=assistant.id).update(content=content, updated_at=datetime.now(timezone.utc))
                if pending:
                    await task_signals.publish(str(task_id))
                last_flush = time.monotonic()

        async def complete(result):
            await before_request()
            assistant.usage['turn_limited'] = deps.turn_limited
            if isinstance(result.output, CreationReply):
                saved_memories = await creation_memory.save(user_message, result.output.constraints)
                assistant.usage['remembered_rules'] = [{'content': m.content, 'scope': m.scope} for m in saved_memories]
            await assistant.save(update_fields=['usage'])
            await AgentMessage.filter(id=assistant.id).update(native_messages=json.loads(result.new_messages_json()))
            final_text = result.output.message if isinstance(result.output, CreationReply) else result.output
            if request_params.get('has_creation_plan'):
                # Preparing a plan is not a production receipt. Do not let a
                # conversational closing sentence misreport it as completed work.
                final_text = localized_message('创作方案已准备，请核对下方的范围和操作后确认执行。')
            yield TextMessageStartEvent(message_id=final_message_id)
            yield TextMessageContentEvent(message_id=final_message_id, delta=final_text)
            yield TextMessageEndEvent(message_id=final_message_id)

        deps = CreationAgentDeps(service=service, context=context, source_message=user_message,
                                 context_loader=refresh_context, changes=changes if progressive else None, limits=limits)
        deps.creation_rules_seen = {item['chapter_id']: item['constraints_for_new_objects']
                                    for item in context.get('creation_contexts', [])}
        from services.creation_agent.skill_execution import SkillExecution, current_execution
        from utils.prompt_language import skill_workflow
        mode_token = skill_workflow.set(bool(request_params.get("skill_snapshot")))
        execution_token = None
        if request_params.get('skill_snapshot'):
            execution_token = current_execution.set(SkillExecution(request_params, assistant, before_request))
        try:
            execution = current_execution.get()
            routed_start = bool(not deep and progressive and not request.targets and request.write_scope in {'chapter', 'project'}
                and not request.production_intents and execution and 'creation_planning' in execution.snapshot.contents)
            if routed_start:
                # Broad production requests must not depend on the chat model
                # choosing submit_production instead of emitting a huge CRUD call.
                last_event = await agent_event_log.last(assistant)
                if last_event is None or last_event['type'] in {'RUN_ERROR', 'RUN_FINISHED'}:
                    buffer.append({'type': 'RUN_STARTED', 'runId': task_id, 'threadId': str(conversation.id)})
                    await flush()
                from services.creation_agent.plans import CreationPlanner
                from pydantic_ai.exceptions import UnexpectedModelBehavior
                try:
                    plan = await CreationPlanner(execution, user_message).prepare(request)
                except UnexpectedModelBehavior:
                    raise ValueError(localized_message('助手未能完成内部内容校验，已保留已完成步骤，可继续本次任务。')) from None
                if plan is not None:
                    content = localized_message('创作方案已准备，请核对下方的范围和操作后确认执行。')
                    buffer.extend([
                        {'type': 'TEXT_MESSAGE_START', 'messageId': final_message_id, 'role': 'assistant'},
                        {'type': 'TEXT_MESSAGE_CONTENT', 'messageId': final_message_id, 'delta': content},
                        {'type': 'TEXT_MESSAGE_END', 'messageId': final_message_id},
                        {'type': 'RUN_FINISHED', 'runId': task_id, 'threadId': str(conversation.id)},
                    ])
                    await flush()
                    return {'conversation_id': conversation.id, 'change_ids': [], 'plan_prepared': True}
            if deep:
                from services.creation_agent.deep_execution import stream_deep_agent
                events = stream_deep_agent(request=request, conversation=conversation, assistant=assistant,
                    deps=deps, recorded=recorded_model, execution=execution, before_request=before_request,
                    model_settings=limits.output_model_settings(chosen.max_tokens))
            else:
                history = await prepare_history(conversation, assistant, limits, recorded_model)
                context['conversation_summary'] = conversation.summary
                events = stream_creation_agent(
                    message=request.message, conversation_id=str(conversation.id), run_id=task_id,
                    model=recorded_model, deps=deps,
                    usage_limits=UsageLimits(request_limit=limits.request_limit, tool_calls_limit=limits.tool_calls_limit,
                                             total_tokens_limit=limits.total_tokens_limit),
                    model_settings=limits.output_model_settings(chosen.max_tokens),
                    message_history=history, on_complete=complete,
                )
            async for event in events:
                item = event if isinstance(event, dict) else event.model_dump(mode="json", by_alias=True, exclude_none=True)
                kind = item["type"]
                if routed_start and kind == 'RUN_STARTED':
                    continue
                item["timestamp"] = int(time.time() * 1000)
                if not deep and kind.startswith('TEXT_MESSAGE') and item.get('messageId') != final_message_id:
                    # Some models put planning/retries in ordinary content.
                    # Stream tool progress, then publish only the validated reply.
                    continue
                if kind == "RUN_ERROR":
                    error = public_run_error(item.get('message', ''), recorded_model.calls,
                                             turn_limited=deps.turn_limited)
                    item["message"] = error
                if kind == "TEXT_MESSAGE_START":
                    # AG-UI emits one text message per model response. Persist
                    # the latest message just as HttpAgent's textMessageBuffer
                    # does, rather than restoring every intermediate preamble.
                    content = ""
                elif kind == "TEXT_MESSAGE_CONTENT":
                    content += item.get("delta", "")
                if buffer and kind in {"TEXT_MESSAGE_CONTENT", "THINKING_TEXT_MESSAGE_CONTENT", "REASONING_MESSAGE_CONTENT", "TOOL_CALL_ARGS"} and buffer[-1]["type"] == kind and (
                    buffer[-1].get("messageId") == item.get("messageId") and buffer[-1].get("toolCallId") == item.get("toolCallId")
                ):
                    buffer[-1]["delta"] += item.get("delta", "")
                else:
                    buffer.append(item)
                if time.monotonic() - last_flush >= 0.2 or kind not in {"TEXT_MESSAGE_CONTENT", "THINKING_TEXT_MESSAGE_CONTENT", "REASONING_MESSAGE_CONTENT", "TOOL_CALL_ARGS"}:
                    await flush()
            if error:
                raise ValueError(error)
            return {"conversation_id": conversation.id,
                    "change_ids": await PromptChange.filter(task_id=task_id).values_list("id", flat=True),
                    "token_usage": assistant.usage}
        finally:
            skill_workflow.reset(mode_token)
            if execution_token is not None:
                current_execution.reset(execution_token)
            await flush()
            if isinstance(model, OpenAIChatModel):
                await model.client.close()
