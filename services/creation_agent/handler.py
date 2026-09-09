"""Run a private creation conversation inside the existing AI task executor."""

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
from services.creation_agent.sessions import agent_configuration, agent_models
from services.creation_agent.tools import PromptEditService
from services.creation_agent.memory import creation_memory
from services.creation_agent.history import prepare_history
from utils.enums import TaskStatusEnum, UserStatusEnum


async def authorize_run(params: dict) -> AuthContext:
    ctx = AuthContext()
    if settings.AUTH_ENABLED:
        from auth.models import User
        user = await User.get_or_none(id=params.get("user_id"), status=UserStatusEnum.active.value)
        if user is None:
            raise HTTPException(403, "运行用户已不可用")
        headers = [(b"x-team-id", str(params["team_id"]).encode())] if params.get("team_id") else []
        ctx = await get_auth_context(Request({"type": "http", "headers": headers}), user=user)
    await require_roles("admin", "creator")(ctx)
    await ensure_novel_access(params["novel_id"], ctx)
    return ctx


def configured_model(config, limits: AgentConfiguration):
    client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key,
                         max_retries=0, timeout=limits.timeout_seconds)
    extra_body = {}
    if getattr(config, 'thinking', None) in ('enabled', 'disabled'):
        extra_body['thinking'] = {'type': config.thinking}
    return UsagePreservingChatModel(config.model, provider=OpenAIProvider(openai_client=client),
                                   settings={'extra_body': extra_body})


def chapter_context(chapter: Chapter | None, character_budget: int, offset: int | None = None) -> dict | None:
    if chapter is None:
        if offset is not None:
            raise ValueError('当前请求未选择章节，不能读取章节片段')
        return None
    content = chapter.content or ""
    total = len(content)
    if offset is not None:
        if offset < 0 or offset > total:
            raise ValueError('章节读取位置超出正文范围，请根据 content_characters 调整')
        end = min(total, offset + character_budget)
        return {"id": chapter.id, "number": chapter.number, "name": chapter.name,
                "content_excerpt": content[offset:end], "content_truncated": offset > 0 or end < total,
                "content_characters": total, "content_offset": offset,
                "content_next_offset": end if end < total else None}
    truncated = len(content) > character_budget
    if truncated:
        half = max(1, character_budget // 2)
        content = f"{content[:half]}\n[…章节中部未载入…]\n{content[-half:]}"
    return {"id": chapter.id, "number": chapter.number, "name": chapter.name,
            "content_excerpt": content, "content_truncated": truncated,
            "content_characters": total, "content_offset": 0,
                "content_next_offset": character_budget // 2 if truncated else None}


def public_run_error(message: str, calls: list[dict]) -> str:
    """Return actionable fixed copy without disclosing a provider's error payload."""
    if '上下文超过配置上限' in message:
        return '当前内容超过助手的上下文额度。请减少选中的对象，或在助手设置提高上下文额度后重试。'
    if '本轮模型调用次数已达到配置上限' in message or 'request_limit' in message:
        return '本轮处理次数已达到上限。已保存的修改可在记录中查看，请继续描述尚未完成的调整。'
    if '本轮 token 消耗已达到配置上限' in message or 'total_tokens_limit' in message:
        return '本轮用量已达到上限。已保存的修改可在记录中查看，请继续描述尚未完成的调整。'
    last_finish = next((call['finish_reason'] for call in reversed(calls) if call.get('finish_reason')), None)
    if last_finish == 'length':
        return '模型本次输出达到上限，未能完成要求。请在助手设置提高单次输出上限，或切换模型后重试。'
    return '创作助手执行失败。请查看已保存的修改，确认模型可用后重试。'


class CreationAgentTaskHandler(BaseTaskHandler):
    def timeout_seconds(self, request_params: dict) -> int:
        return AgentConfiguration.model_validate(request_params.get("agent_configuration", {})).timeout_seconds

    async def execute(self, request_params: dict) -> dict:
        task_id = request_params["task_id"]
        user_message = await AgentMessage.get(task_id=task_id, role="user")
        assistant = await AgentMessage.get(task_id=task_id, role="assistant")
        conversation = await AgentConversation.get(id=assistant.conversation_id)
        request = AgentRunRequest.model_validate(user_message.run_input)
        limits = AgentConfiguration.model_validate(request_params["agent_configuration"])

        async def before_request():
            ctx = await authorize_run(request_params)
            if not (await agent_configuration()).enabled:
                raise ValueError("创作助手已停用")
            if not await AiTask.filter(id=task_id, status=TaskStatusEnum.running.value).exists():
                raise ValueError("运行已停止，不能继续请求模型或写入")
            chosen = next((config for config in await agent_models(ctx) if config.id == request_params["model_config_id"]), None)
            if chosen is None:
                raise ValueError("运行模型已停用或不可访问，请重新选择模型")
            return chosen

        chosen = await before_request()
        service = PromptEditService(novel_id=conversation.novel_id, task_id=assistant.task_id,
            allowed_targets={(target.kind, target.id) for target in request.targets},
            max_batch_size=limits.max_targets, authorization_check=before_request)
        novel = await Novel.get(id=conversation.novel_id)
        chapter = await Chapter.get_or_none(id=request.chapter_id, novel_id=novel.id) if request.chapter_id else None
        context = {"project": {"id": novel.id, "name": novel.name, "outline": novel.story_outline,
                              "setting": novel.project_setting, "style": novel.custom_style_prompt or novel.style_key},
                   "chapter": chapter_context(chapter, max(500, limits.max_context_characters // 3)),
                   "conversation_summary": conversation.summary}
        context['constraints'] = await creation_memory.applicable(novel.id, request)
        async def refresh_context(chapter_offset: int | None = None):
            await before_request()
            await novel.refresh_from_db()
            current_chapter = await Chapter.get_or_none(id=request.chapter_id, novel_id=novel.id) if request.chapter_id else None
            context['chapter'] = chapter_context(current_chapter, max(500, limits.max_context_characters // 3), chapter_offset)
            context['project'].update(outline=novel.story_outline, setting=novel.project_setting,
                                      style=novel.custom_style_prompt or novel.style_key)
            context['constraints'] = await creation_memory.applicable(novel.id, request)
            return context

        async def check_context():
            if await creation_memory.applicable(novel.id, request) != context['constraints']:
                raise ValueError('适用的创作约束已被更新，请重新读取上下文后再修改')
            return context['constraints']

        service.context_check = check_context
        model = configured_model(chosen, limits)
        recorded_model = RecordedAgentModel(model, message=assistant, before_request=before_request,
            max_characters=min(limits.max_context_characters, chosen.max_context_characters or limits.max_context_characters),
            request_limit=limits.request_limit, total_tokens_limit=limits.total_tokens_limit)
        persisted = []
        buffer = []
        content = ""
        last_flush = time.monotonic()
        error = ''

        async def flush():
            nonlocal last_flush
            if buffer:
                persisted.extend(buffer)
                buffer.clear()
            await AgentMessage.filter(id=assistant.id).update(events=persisted, content=content, updated_at=datetime.now(timezone.utc))
            last_flush = time.monotonic()

        async def complete(result):
            await before_request()
            if isinstance(result.output, CreationReply):
                await creation_memory.save(user_message, result.output.constraints)
            await AgentMessage.filter(id=assistant.id).update(native_messages=json.loads(result.new_messages_json()))
            if isinstance(result.output, CreationReply):
                message_id = f'{task_id}:reply'
                yield TextMessageStartEvent(message_id=message_id)
                yield TextMessageContentEvent(message_id=message_id, delta=result.output.message)
                yield TextMessageEndEvent(message_id=message_id)

        try:
            history = await prepare_history(conversation, assistant, limits, recorded_model)
            context['conversation_summary'] = conversation.summary
            async for event in stream_creation_agent(
                message=request.message, conversation_id=str(conversation.id), run_id=task_id,
                model=recorded_model, deps=CreationAgentDeps(service=service, context=context, source_message=user_message, context_loader=refresh_context),
                usage_limits=UsageLimits(request_limit=limits.request_limit, tool_calls_limit=limits.tool_calls_limit,
                                         total_tokens_limit=limits.total_tokens_limit),
                model_settings={"max_tokens": min(limits.max_output_tokens, chosen.max_tokens or limits.max_output_tokens)},
                message_history=history, on_complete=complete,
            ):
                item = event.model_dump(mode="json", by_alias=True, exclude_none=True)
                kind = item["type"]
                if kind.startswith('THINKING'):
                    # Provider reasoning stays in native model history; the UI
                    # needs progress and results, not thousands of reasoning chunks.
                    continue
                if kind == "RUN_ERROR":
                    error = public_run_error(item.get('message', ''), recorded_model.calls)
                    item["message"] = error
                if kind == "TEXT_MESSAGE_START":
                    # AG-UI emits one text message per model response. Persist
                    # the latest message just as HttpAgent's textMessageBuffer
                    # does, rather than restoring every intermediate preamble.
                    content = ""
                elif kind == "TEXT_MESSAGE_CONTENT":
                    content += item.get("delta", "")
                if buffer and kind in {"TEXT_MESSAGE_CONTENT", "TOOL_CALL_ARGS"} and buffer[-1]["type"] == kind and (
                    buffer[-1].get("messageId") == item.get("messageId") and buffer[-1].get("toolCallId") == item.get("toolCallId")
                ):
                    buffer[-1]["delta"] += item.get("delta", "")
                else:
                    buffer.append(item)
                if time.monotonic() - last_flush >= 0.2 or kind not in {"TEXT_MESSAGE_CONTENT", "TOOL_CALL_ARGS"}:
                    await flush()
            if error:
                raise ValueError(error)
            return {"conversation_id": conversation.id,
                    "change_ids": await PromptChange.filter(task_id=task_id).values_list("id", flat=True),
                    "token_usage": assistant.usage}
        finally:
            await flush()
            if isinstance(model, OpenAIChatModel):
                await model.client.close()
