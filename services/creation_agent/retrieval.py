"""Private, paged recovery of context archives and conversation evidence."""

from tortoise.expressions import Q
from models.creation_agent import AgentContextCheckpoint, AgentMessage
from services.creation_agent.context_budget import encode


async def read_history(source, *, query='', before=None, archive_id=None, offset=0, limit=2000):
    if source is None:
        return {'items': [], 'next_before': None}
    if archive_id is not None:
        row = await AgentContextCheckpoint.get_or_none(id=archive_id, conversation_id=source.conversation_id)
        if row is None:
            raise ValueError('当前会话中没有该历史引用')
        content = encode(row.payload)
        if offset > len(content):
            raise ValueError('历史读取位置超出范围')
        return {'archive_id': row.id, 'content': content[offset:offset + limit],
                'content_truncated': offset > 0 or offset + limit < len(content),
                'next_offset': offset + limit if offset + limit < len(content) else None,
                'total_characters': len(content), 'historical': True}
    rows = AgentMessage.filter(conversation_id=source.conversation_id, id__lt=min(before or source.id, source.id))
    if query:
        rows = rows.filter(Q(content__icontains=query))
    records = await rows.order_by('-id').limit(7).prefetch_related('task')
    page = records[:6]
    return {'items': [{'message_id': row.id, 'role': row.role, 'content': row.content[:limit // 6],
                      'content_truncated': len(row.content) > limit // 6, 'status': row.task.status,
                      'targets': (row.run_input or {}).get('targets', [])} for row in reversed(page)],
            'next_before': page[-1].id if len(records) > 6 else None}
