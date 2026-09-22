"""Safe result projections reconstructed from server-owned tool events."""

import json

from models.creation_agent import AgentMessage, PromptChange


def tool_results(message: AgentMessage):
    names = {event.get('toolCallId'): event.get('toolCallName') for event in message.events or [] if event.get('type') == 'TOOL_CALL_START'}
    for event in message.events or []:
        if event.get('type') != 'TOOL_CALL_RESULT':
            continue
        value = event.get('content')
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                continue
        if isinstance(value, dict):
            yield names.get(event.get('toolCallId')), value


def query_results(message: AgentMessage) -> list[dict]:
    results = []
    for name, value in tool_results(message):
        if name == 'get_creation_context':
            value = value.get('catalog') or {}
        elif name != 'query_creation_objects':
            continue
        if not isinstance(value.get('items'), list):
            continue
        items = []
        for item in value['items'][:30]:
            if not isinstance(item, dict) or item.get('kind') not in {'asset', 'variant', 'scene', 'chapter'}:
                continue
            if not isinstance(item.get('id'), int) or not isinstance(item.get('name'), str):
                continue
            items.append({key: item[key] for key in ('kind', 'id', 'name', 'asset_id', 'chapter_id') if key in item})
        results.append({'items': items, 'total': value.get('total', len(items)), 'has_more': bool(value.get('next_page'))})
    return results


async def message_changes(message: AgentMessage, novel_id: int) -> list[PromptChange]:
    rows = await PromptChange.filter(task_id=message.task_id, novel_id=novel_id).order_by('id')
    ids = {value['change_id'] for name, value in tool_results(message)
           if name == 'undo_creation_change' and isinstance(value.get('change_id'), int)}
    if ids:
        own_tasks = await AgentMessage.filter(conversation_id=message.conversation_id).values_list('task_id', flat=True)
        extra = await PromptChange.filter(id__in=ids, novel_id=novel_id, task_id__in=own_tasks).order_by('id')
        rows.extend(row for row in extra if row.id not in {item.id for item in rows})
    return rows
