"""Safe result projections reconstructed from server-owned tool events."""

import json

from models.creation_agent import AgentMessage, PromptChange


def tool_results(events: list[dict]):
    names = {event.get('toolCallId'): event.get('toolCallName') for event in events if event.get('type') == 'TOOL_CALL_START'}
    for event in events:
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


def query_results(events: list[dict]) -> list[dict]:
    results = []
    for name, value in tool_results(events):
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


def undo_change_ids(events: list[dict]) -> set[int]:
    return {value['change_id'] for name, value in tool_results(events)
            if name == 'undo_creation_change' and isinstance(value.get('change_id'), int)}


async def message_changes(message: AgentMessage, novel_id: int, events: list[dict]) -> list[PromptChange]:
    from models.agent_operation import AgentOperation
    children = await AgentOperation.filter(task_id=message.task_id, key__startswith='submit:', state='completed')
    ids = [message.task_id, *[row.result['task_id'] for row in children if row.result.get('task_id')]]
    rows = await PromptChange.filter(task_id__in=ids, novel_id=novel_id).order_by('id')
    ids = undo_change_ids(events)
    if ids:
        own_tasks = await AgentMessage.filter(conversation_id=message.conversation_id).values_list('task_id', flat=True)
        extra = await PromptChange.filter(id__in=ids, novel_id=novel_id, task_id__in=own_tasks).order_by('id')
        rows.extend(row for row in extra if row.id not in {item.id for item in rows})
    return rows


async def changes_by_message(messages: list[AgentMessage], novel_id: int,
                             events_by_message: dict[int, list[dict]]) -> dict[int, list[PromptChange]]:
    """Batch projection for history pages: one receipt query instead of one per message."""
    if not messages:
        return {}
    grouped: dict[int, list[PromptChange]] = {}
    for change in await PromptChange.filter(task_id__in=[message.task_id for message in messages],
                                            novel_id=novel_id).order_by('id'):
        grouped.setdefault(change.task_id, []).append(change)
    from models.agent_operation import AgentOperation
    children = await AgentOperation.filter(task_id__in=[message.task_id for message in messages], key__startswith='submit:', state='completed')
    owners = {row.result['task_id']: row.task_id for row in children if row.result.get('task_id')}
    for change in await PromptChange.filter(task_id__in=list(owners), novel_id=novel_id).order_by('id'):
        grouped.setdefault(owners[str(change.task_id)], []).append(change)
    result = {message.id: list(grouped.get(message.task_id, [])) for message in messages}
    referenced: dict[int, list[int]] = {}
    for message in messages:
        for change_id in undo_change_ids(events_by_message.get(message.id, [])):
            referenced.setdefault(change_id, []).append(message.id)
    if referenced:
        own_tasks = await AgentMessage.filter(conversation_id__in={message.conversation_id for message in messages}
                                              ).values_list('task_id', flat=True)
        extra = await PromptChange.filter(id__in=list(referenced), novel_id=novel_id, task_id__in=own_tasks).order_by('id')
        for change in extra:
            for message_id in referenced[change.id]:
                holder = result[message_id]
                if change.id not in {item.id for item in holder}:
                    holder.append(change)
    return result
