"""Incremental conversation compression; durable creative constraints remain separate."""

from dataclasses import replace
import json
import asyncio

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
    UserPromptPart,
    TextPart,
)
from pydantic_ai.usage import UsageLimits

from models.creation_agent import AgentConversation, AgentMessage, AgentContextCheckpoint
from prompts.creation_agent import CREATION_SUMMARY_INSTRUCTIONS, render_creation_summary
from schemas.creation_agent import AgentConfiguration


summary_agent = Agent(instructions=CREATION_SUMMARY_INSTRUCTIONS, name='creation_history_summary')


def _compact_retry_content(content: list[dict] | str) -> str:
    if isinstance(content, str):
        return content if len(content) <= 1200 else f'{content[:1200]}…'
    errors = []
    for item in content[:12]:
        location = '.'.join(str(value) for value in item.get('loc', ()))
        message = str(item.get('msg') or '参数无效').removeprefix('Value error, ')
        errors.append(f'{location}: {message}' if location else message)
    suffix = '\n其余错误已省略，请先修正以上字段。' if len(content) > len(errors) else ''
    return '工具参数校验失败：\n' + '\n'.join(errors) + suffix


def compact_retry_history(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Keep retry guidance while removing rejected payloads from later model calls.

    Pydantic validation errors include the complete invalid input. For long scene
    prompts that duplicates the prompt in both the failed tool call and its retry
    message, so a few corrections can exhaust the context budget even for one
    selected scene.
    """
    failed_call_ids = {
        part.tool_call_id
        for message in messages if isinstance(message, ModelRequest)
        for part in message.parts if isinstance(part, RetryPromptPart) and part.tool_call_id
    }
    if not failed_call_ids:
        return messages

    compacted = []
    for message in messages:
        parts = []
        changed = False
        for part in message.parts:
            if isinstance(part, ToolCallPart) and part.tool_call_id in failed_call_ids:
                part = replace(part, args={'retry_context': '未通过校验的完整参数已省略，请按后续错误修正'})
                changed = True
            elif isinstance(part, RetryPromptPart):
                content = _compact_retry_content(part.content)
                if content != part.content:
                    part = replace(part, content=content)
                    changed = True
            parts.append(part)
        if changed and isinstance(message, (ModelRequest, ModelResponse)):
            message = replace(message, parts=parts)
        compacted.append(message)
    return compacted


async def prepare_history(conversation: AgentConversation, assistant: AgentMessage, limits: AgentConfiguration, model):
    """Load a bounded tail; unresolved older history is recoverable, never re-injected wholesale."""
    query = AgentMessage.filter(conversation=conversation, role='assistant', id__lt=assistant.id,
                               id__gt=conversation.summary_until_id)
    previous = await query.order_by('-id').limit(max(32, limits.history_runs * 4))
    recent = []
    characters = 0
    history_budget = min(limits.max_context_characters // 3, limits.working_input_tokens)
    from services.creation_agent.context_budget import wire_size
    from pydantic_ai.models import ModelRequestParameters
    # Small conversations can append to an unchanged prefix. A turn-count-only
    # sliding window would rewrite the summary after every sixth short message.
    for message in previous:
        native = ModelMessagesTypeAdapter.validate_python(message.native_messages) if message.native_messages else []
        size = wire_size(native, ModelRequestParameters())['total_characters'] if native else len(message.content) + 800
        if characters + size > history_budget * limits.compaction_trigger_ratio:
            break
        recent.append(message)
        characters += size
    cutoff = recent[-1].id if recent else assistant.id
    older = await query.filter(id__lt=cutoff).order_by('id').limit(limits.history_runs)
    if older:
        records = await AgentMessage.filter(conversation=conversation,
            task_id__in=[m.task_id for m in older]).order_by('id').only('id', 'role', 'content', 'run_input')
        budget = max(64, min(800, history_budget // (2 * max(len(records), 1))))
        data = [{'message_id': m.id, 'role': m.role, 'content': m.content[:budget],
                 'targets': (m.run_input or {}).get('targets', []),
                 'truncated': len(m.content) > budget} for m in records]
        # Fallback is an extractive checkpoint, not a fabricated successful summary.
        excerpt = '\n'.join(f"[{item['message_id']}] {item['role']}: {item['content']}" for item in data)
        summary = (conversation.summary + '\n' + excerpt)[-history_budget:]
        kind = 'extractive_summary'
        previous_phase = getattr(model, 'phase', 'main')
        try:
            if hasattr(model, 'phase'):
                model.phase = 'summary'
            result = await asyncio.wait_for(summary_agent.run(
                render_creation_summary(conversation.summary[:history_budget], data), model=model,
                model_settings={'max_tokens': min(limits.summary_output_tokens, limits.max_output_tokens)},
                usage_limits=UsageLimits(request_limit=1)), timeout=limits.summary_timeout_seconds)
            if not isinstance(result.output, str) or not result.output.strip():
                raise ValueError('empty summary')
            summary = result.output[:history_budget]
            kind = 'summary'
        except Exception:
            # Cancellation must propagate. Failures of this optional compression
            # model never force the main agent to consume an unbounded history.
            pass
        finally:
            if hasattr(model, 'phase'):
                model.phase = previous_phase
        await AgentContextCheckpoint.create(conversation=conversation, message_id=assistant.id,
            until_message_id=older[-1].id, kind=kind, content=summary,
            payload={'source_message_ids': [m.id for m in records]})
        conversation.summary = summary
        conversation.summary_until_id = older[-1].id
        await conversation.save(update_fields=['summary', 'summary_until_id', 'updated_at'])
    history = []
    if conversation.summary:
        history.append(ModelRequest(parts=[UserPromptPart(render_creation_summary(conversation.summary, []))]))
        history.append(ModelResponse(parts=[TextPart('已读取历史摘要；当前业务事实以重新读取的对象为准。')]))
    # The recent tail may not include a large last run. Preserve its user intent
    # and actual outcome, not the full payload that caused the original overflow.
    if not recent and previous:
        last = previous[0]
        user = await AgentMessage.get_or_none(conversation=conversation, task_id=last.task_id, role='user')
        if user:
            history.append(ModelRequest(parts=[UserPromptPart(user.content[:history_budget // 2])]))
        history.append(ModelResponse(parts=[TextPart(last.content[:history_budget // 2] or '上一轮未完成，可查询实际保存回执。')]))
    for message in reversed(recent):
        if message.native_messages:
            history.extend(ModelMessagesTypeAdapter.validate_python(message.native_messages))
        else:
            user = await AgentMessage.get_or_none(conversation=conversation, task_id=message.task_id, role='user')
            if user:
                history.append(ModelRequest(parts=[UserPromptPart(user.content[:800])]))
            history.append(ModelResponse(parts=[TextPart(message.content[:800] or '上一轮未完成，请查询操作记录。')]))
    return history
