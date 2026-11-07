"""Visible execution history reconstructed from real agent events."""

from datetime import datetime, timezone

from models.creation_agent import AgentMessage
from services.creation_agent.event_log import agent_event_log


def event_time(event):
    timestamp = event.get('timestamp')
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat() if timestamp is not None else None


def activity_from_events(events: list[dict], status: int) -> list[dict]:
    items = {}
    thinking = 0
    for event in events:
        kind = event['type']
        when = event_time(event)
        if kind in {'THINKING_TEXT_MESSAGE_START', 'REASONING_MESSAGE_START'}:
            thinking += 1
            key = f'thinking:{thinking}'
            items[key] = {'id': key, 'kind': 'thinking', 'label': '思考过程', 'status': 'running',
                          'detail': '', 'started_at': when}
        elif kind in {'THINKING_TEXT_MESSAGE_CONTENT', 'REASONING_MESSAGE_CONTENT'} and thinking:
            items[f'thinking:{thinking}']['detail'] += event.get('delta', '')
        elif kind in {'THINKING_TEXT_MESSAGE_END', 'REASONING_MESSAGE_END'} and thinking:
            items[f'thinking:{thinking}'].update(status='completed', finished_at=when)
        elif kind == 'TOOL_CALL_START':
            key = f"tool:{event['toolCallId']}"
            items[key] = {'id': key, 'kind': 'tool', 'tool_name': event['toolCallName'],
                          'label': '执行步骤', 'status': 'running', 'started_at': when}
        elif kind == 'TOOL_CALL_RESULT':
            key = f"tool:{event['toolCallId']}"
            if key in items:
                items[key].update(status='completed', finished_at=when)
        elif kind == 'CUSTOM' and event.get('name') == 'agent_activity':
            item = event['value']
            items[item['id']] = dict(item)
    if status in {3, 4, 5}:
        for item in items.values():
            if item['status'] == 'running':
                item['status'] = 'completed' if status == 3 else 'failed'
    return list(items.values())


async def activity_for_messages(messages, events, production):
    """Include submitted jobs and their model steps in the originating chat turn."""
    result = {row.id: activity_from_events(events[row.id], row.task.status) for row in messages}
    if not messages:
        return result
    owners = {}
    for row in messages:
        owners.setdefault(str(row.task_id), []).append(row.id)
        for receipt in production.get(str(row.task_id), []):
            if receipt['task_id'] != str(row.task_id):
                owners.setdefault(receipt['task_id'], []).append(row.id)
    production_messages = await AgentMessage.filter(task_id__in=list(owners), role='assistant')
    conversation_ids = {row.conversation_id for row in messages + production_messages}
    rows = await AgentMessage.filter(conversation_id__in=conversation_ids, role='assistant').select_related('task')
    own_ids = {row.id for row in messages}
    related = [row for row in rows if row.id not in own_ids and (
        str(row.task_id) in owners or row.task.request_params.get('parent_task_id') in owners)]
    child_events = await agent_event_log.load_many(related)
    for row in related:
        owner = str(row.task_id) if str(row.task_id) in owners else row.task.request_params['parent_task_id']
        for item in activity_from_events(child_events[row.id], row.task.status):
            if not item['id'].startswith('model:'):
                item['id'] = f'{row.task_id}:{item["id"]}'
            for message_id in owners[owner]:
                result[message_id].append(item)
    for items in result.values():
        items.sort(key=lambda item: item.get('started_at') or '')
    coalesced = [row for row in messages if (row.run_input or {}).get('creation_run_id')]
    if coalesced:
        from models.agent_operation import AgentOperation
        rows = await AgentOperation.filter(task_id__in=[row.task_id for row in coalesced], key='plan:coalesced', state='completed')
        by_task = {str(row.task_id): {f'creation:step:{member}' for representative, members in row.result['groups'].items()
                    for member in members if member != representative} for row in rows}
        for message in coalesced:
            hidden = by_task.get(str(message.task_id), set())
            result[message.id] = [item for item in result[message.id] if item['id'] not in hidden]
    return result


def run_timing(task, production):
    started_at = task.started_at or task.created_at
    if task.status in {1, 2, 6} or any(item['status'] in {1, 2, 6} for item in production):
        return {'started_at': started_at, 'finished_at': None}
    finishes = [datetime.fromisoformat(item['finished_at']) for item in production if item.get('finished_at')]
    if task.finished_at:
        finishes.append(task.finished_at)
    return {'started_at': started_at, 'finished_at': max(finishes) if finishes else None}
