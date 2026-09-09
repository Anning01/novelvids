"""Incremental conversation compression; durable creative constraints remain separate."""

import json

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.usage import UsageLimits

from models.creation_agent import AgentConversation, AgentMessage
from prompts.creation_agent import CREATION_SUMMARY_INSTRUCTIONS, render_creation_summary
from schemas.creation_agent import AgentConfiguration
from utils.enums import TaskStatusEnum


summary_agent = Agent(instructions=CREATION_SUMMARY_INSTRUCTIONS, name='creation_history_summary')


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
