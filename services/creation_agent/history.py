"""Incremental conversation compression; durable creative constraints remain separate."""

from dataclasses import replace
import json

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
)
from pydantic_ai.usage import UsageLimits

from models.creation_agent import AgentConversation, AgentMessage
from prompts.creation_agent import CREATION_SUMMARY_INSTRUCTIONS, render_creation_summary
from schemas.creation_agent import AgentConfiguration
from utils.enums import TaskStatusEnum


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
    previous = await AgentMessage.filter(conversation=conversation, role='assistant', id__lt=assistant.id, id__gt=conversation.summary_until_id,
        task__status=TaskStatusEnum.completed.value).order_by('-id').only('id', 'task_id', 'native_messages', 'content')
    recent = []
    characters = 0
    for message in previous[:limits.history_runs]:
        size = len(json.dumps(message.native_messages, ensure_ascii=False))
        if characters + size > limits.max_context_characters // 3:
            break
        recent.append(message)
        characters += size
    older = list(reversed(previous[len(recent):]))
    if older:
        # Only a bounded block is summarized per run. Original records remain available.
        block = older[:limits.history_runs]
        records = await AgentMessage.filter(conversation=conversation, task_id__in=[message.task_id for message in block]).order_by('id').only('id', 'role', 'content', 'run_input')
        budget = max(256, limits.max_context_characters // (2 * max(len(records), 1)))
        data = [{'message_id': message.id, 'role': message.role, 'content': message.content[:budget],
                 'targets': (message.run_input or {}).get('targets', []),
                 'truncated': len(message.content) > budget} for message in records]
        result = await summary_agent.run(render_creation_summary(conversation.summary, data), model=model,
            model_settings={'max_tokens': min(1500, limits.max_output_tokens)}, usage_limits=UsageLimits(request_limit=1))
        conversation.summary = result.output
        conversation.summary_until_id = block[-1].id
        await conversation.save(update_fields=['summary', 'summary_until_id', 'updated_at'])
    # Do not silently discard the intermediate unsummarized gap after a failed/bounded summary.
    remaining = [message for message in reversed(previous) if message.id > conversation.summary_until_id and message not in recent]
    ordered = [*remaining, *reversed(recent)]
    return [item for message in ordered for item in ModelMessagesTypeAdapter.validate_python(message.native_messages)]
