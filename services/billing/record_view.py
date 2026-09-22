"""Read-only conversation grouping; never writes or recalculates billing records."""

from decimal import Decimal

from tortoise.queryset import QuerySet

from models.creation_agent import AgentMessage
from models.usage_record import ModelUsageRecord
from schemas.billing import ModelUsageRecordOut
from utils.enums import AiTaskTypeEnum


QUERY_BATCH_SIZE = 500
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens',
                'summary_requests', 'summary_input_tokens', 'summary_output_tokens')


class BillingRecordView:
    """Group only the already-filtered visible ledger, before applying pagination."""

    def __init__(self, query: QuerySet[ModelUsageRecord]):
        self.query = query

    async def _groups(self) -> dict[tuple, list[int]]:
        rows = await self.query.order_by('-id').values('id', 'novel_id', 'ai_task_id', 'task_type', 'team_id', 'currency')
        task_ids = list({row['ai_task_id'] for row in rows
                         if row['task_type'] == AiTaskTypeEnum.creation_agent.value and row['ai_task_id']})
        conversations = {}
        for start in range(0, len(task_ids), QUERY_BATCH_SIZE):
            messages = await AgentMessage.filter(role='assistant', task_id__in=task_ids[start:start + QUERY_BATCH_SIZE]).values(
                'task_id', 'conversation_id', 'conversation__novel_id')
            for message in messages:
                conversations[(message['task_id'], message['conversation__novel_id'])] = message['conversation_id']
        groups = {}
        for row in rows:
            conversation = conversations.get((row['ai_task_id'], row['novel_id'])) if row['task_type'] == AiTaskTypeEnum.creation_agent.value else None
            # Currency/team boundaries remain explicit even for inconsistent old data.
            key = ('conversation', conversation, row['novel_id'], row['team_id'], row['currency']) if conversation else ('record', row['id'])
            groups.setdefault(key, []).append(row['id'])
        return groups

    async def _records(self, ids: list[int]) -> list[ModelUsageRecord]:
        records = []
        for start in range(0, len(ids), QUERY_BATCH_SIZE):
            records.extend(await self.query.filter(id__in=ids[start:start + QUERY_BATCH_SIZE]))
        return sorted(records, key=lambda item: item.id, reverse=True)

    @staticmethod
    def _conversation(records: list[ModelUsageRecord], conversation_id: int) -> ModelUsageRecordOut:
        latest = records[0]
        row = ModelUsageRecordOut.model_validate(latest)
        usage = {key: sum(int(record.usage.get(key) or 0) for record in records) for key in TOKEN_FIELDS}
        usage['requests'] = sum(int(record.usage.get('requests') or 1) for record in records)
        usage['missing_usage'] = any(record.usage.get('missing_usage') for record in records)
        usage['cache_usage_reported'] = all(record.usage.get('cache_usage_reported') is True for record in records)
        sources = {record.cost_source for record in records}
        # No single price/discount/model config can describe a mixed conversation.
        return row.model_copy(update={
            'record_kind': 'agent_conversation', 'conversation_id': conversation_id,
            'record_count': len(records), 'turn_count': len({record.ai_task_id for record in records}),
            'statuses': sorted({record.status for record in records}),
            'cost': float(sum((record.cost for record in records), Decimal('0'))),
            'usage': usage, 'ai_task_id': None, 'model_config_id': None, 'pricing_snapshot': None,
            'model': '、'.join(sorted({record.model for record in records})),
            'model_name': '、'.join(sorted({record.model_name or record.model for record in records})),
            'cost_source': next(iter(sources)) if len(sources) == 1 else 'mixed',
            'duration_seconds': sum(record.duration_seconds for record in records)
                if all(record.duration_seconds is not None for record in records) else None,
            'user_id': latest.user_id if all(record.user_id == latest.user_id for record in records) else None,
            'updated_at': max(record.updated_at for record in records),
        })

    @staticmethod
    def _page(items: list[ModelUsageRecordOut], total: int, params) -> dict:
        return {'items': items, 'pagination': {'total': total, 'page': params.page,
            'page_size': params.page_size, 'pages': (total + params.page_size - 1) // params.page_size}}

    async def list(self, params) -> dict:
        groups = await self._groups()
        start = (params.page - 1) * params.page_size
        visible = list(groups.items())[start:start + params.page_size]
        rows = {row.id: row for row in await self._records([id for _, ids in visible for id in ids])}
        items = []
        for key, ids in visible:
            records = [rows[id] for id in ids if id in rows]
            if not records:
                continue
            items.append(self._conversation(records, key[1]) if key[0] == 'conversation'
                         else ModelUsageRecordOut.model_validate(records[0]))
        return self._page(items, len(groups), params)

    async def details(self, record_id: int, params) -> dict:
        groups = await self._groups()
        ids = next((ids for ids in groups.values() if record_id in ids), None)
        if ids is None:
            raise LookupError('当前范围内不存在该流水')
        start = (params.page - 1) * params.page_size
        rows = await self._records(ids[start:start + params.page_size])
        return self._page([ModelUsageRecordOut.model_validate(row) for row in rows], len(ids), params)
