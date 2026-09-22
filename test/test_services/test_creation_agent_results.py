import json
import pytest

from ag_ui.core import ToolCallResultEvent, ToolCallStartEvent

from models.creation_agent import AgentMessage
from services.creation_agent.results import query_results, tool_results


def recorded_message(name, value):
    events = [
        ToolCallStartEvent(tool_call_id='query', tool_call_name=name),
        ToolCallResultEvent(tool_call_id='query', message_id='receipt', content=json.dumps(value)),
    ]
    return AgentMessage(events=[event.model_dump(mode='json', by_alias=True) for event in events])


def test_standard_agui_query_receipt_produces_safe_navigation_cards():
    message = recorded_message('query_creation_objects', {
        'items': [{'kind': 'asset', 'id': 7, 'name': '蓝色雨衣', 'prompt': '只供模型读取'},
                  {'kind': 'variant', 'id': 8, 'asset_id': 7, 'name': '夜景形态'}],
        'total': 3, 'next_page': 2,
    })
    assert query_results(message) == [{'items': [
        {'kind': 'asset', 'id': 7, 'name': '蓝色雨衣'},
        {'kind': 'variant', 'id': 8, 'asset_id': 7, 'name': '夜景形态'},
    ], 'total': 3, 'has_more': True}]


def test_standard_agui_undo_receipt_is_recoverable_from_history():
    receipt = {'change_id': 8, 'status': 'reverted'}
    assert list(tool_results(recorded_message('undo_creation_change', receipt))) == [('undo_creation_change', receipt)]


def test_malformed_or_unrelated_tool_receipts_do_not_create_query_cards():
    message = recorded_message('get_creation_context', {'items': []})
    message.events.append({'type': 'TOOL_CALL_RESULT', 'toolCallId': 'query', 'content': 'invalid'})
    assert query_results(message) == []


@pytest.mark.asyncio
async def test_undo_message_projects_only_receipts_from_its_own_conversation():
    from models.ai_task import AiTask
    from models.creation_agent import AgentConversation, PromptChange
    from models.novel import Novel
    from services.creation_agent.results import message_changes

    novel = await Novel.create(name='回执隔离')
    own = await AgentConversation.create(novel=novel)
    other = await AgentConversation.create(novel=novel)
    receipts = []
    for conversation in (own, other):
        task = await AiTask.create(task_type=1, status=3)
        await AgentMessage.create(conversation=conversation, task=task, role='user', request_id=task.id, request_hash='query')
        receipts.append(await PromptChange.create(novel=novel, task=task, tool_call_id='delete', request_hash='delete', changes=[]))
    task = await AiTask.create(task_type=1, status=3)
    message = recorded_message('undo_creation_change', {'change_id': receipts[0].id, 'status': 'reverted'})
    message.conversation_id, message.task_id = own.id, task.id
    assert [row.id for row in await message_changes(message, novel.id)] == [receipts[0].id]
    message.events[-1]['content'] = json.dumps({'change_id': receipts[1].id, 'status': 'reverted'})
    assert await message_changes(message, novel.id) == []
