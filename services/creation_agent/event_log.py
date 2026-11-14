"""Append-only AG-UI event storage with a legacy JSON fallback.

Runs used to persist every event inside ``AgentMessage.events``, which forced a
full-array rewrite on each flush. New events are appended as rows instead; the
JSON array stays readable so records written before the switch still replay.
"""

import json
from collections import OrderedDict
from tortoise import connections
from tortoise.functions import Max
from models.creation_agent import AgentEvent, AgentMessage


class AgentEventLog:
    """Linear-time persistence and paged reads for one message's event log."""

    def __init__(self):
        self.projections = OrderedDict()

    async def size(self, message: AgentMessage) -> int:
        last = await AgentEvent.filter(message_id=message.id).order_by('-seq').limit(1).values_list('seq', flat=True)
        return last[0] + 1 if last else len(message.events or [])

    async def start(self, message: AgentMessage) -> int:
        """Return the next free sequence, adopting legacy JSON events once."""
        existing = await AgentEvent.filter(message_id=message.id).order_by('-seq').limit(1).values_list('seq', flat=True)
        if existing:
            return existing[0] + 1
        legacy = list(message.events or [])
        if legacy:
            await AgentEvent.bulk_create([AgentEvent(message_id=message.id, seq=index, event=item)
                                          for index, item in enumerate(legacy)])
        return len(legacy)

    async def append(self, message_id: int, items: list[dict], seq: int) -> int:
        """Append one flush's events in a single insert and return the next sequence."""
        if not items:
            return seq
        await AgentEvent.bulk_create([AgentEvent(message_id=message_id, seq=seq + offset, event=item)
                                      for offset, item in enumerate(items)])
        return seq + len(items)

    async def load(self, message: AgentMessage) -> list[dict]:
        events = await AgentEvent.filter(message_id=message.id).order_by('seq').values_list('event', flat=True)
        if events:
            return list(events)
        return list(message.events or [])

    async def load_many(self, messages: list[AgentMessage]) -> dict[int, list[dict]]:
        """Load several logs in one query; messages without rows keep their JSON events."""
        loaded = {message.id: list(message.events or []) for message in messages}
        if not messages:
            return loaded
        rows: dict[int, list[dict]] = {}
        stored = await AgentEvent.filter(message_id__in=list(loaded)).order_by('message_id', 'seq').values_list('message_id', 'event')
        for message_id, event in stored:
            rows.setdefault(message_id, []).append(event)
        loaded.update(rows)
        return loaded

    async def page(self, message: AgentMessage, cursor: int, limit: int) -> list[dict]:
        """Read up to ``limit`` events from ``cursor`` on, log storage first."""
        events = await AgentEvent.filter(message_id=message.id, seq__gte=cursor).order_by('seq').limit(limit).values_list('event', flat=True)
        if events:
            return list(events)
        legacy = list(message.events or [])
        return legacy[cursor:cursor + limit]

    async def load_projection_many(self, messages: list[AgentMessage]) -> dict[int, list[dict]]:
        """Read latest cumulative activity states, not gigabytes of superseded text.

        Raw events remain intact for audits and stream replay. Delta events are
        retained because they contain new text rather than cumulative snapshots.
        """
        loaded = {message.id: list(message.events or []) for message in messages}
        if not messages:
            return loaded
        db = connections.get('default')
        versions = await AgentEvent.filter(message_id__in=list(loaded)).annotate(last=Max('seq')).group_by('message_id').values('message_id', 'last')
        missing = {}
        for row in versions:
            identifier, version = row['message_id'], row['last']
            key = (db, identifier)
            cached = self.projections.get(key)
            if cached and cached[0] == version:
                loaded[identifier] = cached[1]
                self.projections.move_to_end(key)
            else:
                missing[identifier] = version
        if missing:
            from models.agent_operation import AgentOperation
            saved = await AgentOperation.filter(key__in=[f'view:events:{identifier}' for identifier in missing],
                task_id__in=[message.task_id for message in messages], state='completed')
            for row in saved:
                identifier = int(row.key.rsplit(':', 1)[1])
                if row.result.get('seq') == missing.get(identifier) and row.result.get('projection_version') == 1:
                    loaded[identifier] = row.result['events']
                    self.projections[(db, identifier)] = (missing.pop(identifier), loaded[identifier])
        if missing:
            postgres = db.capabilities.dialect == 'postgres'
            field = lambda name: f"event->>'{name}'" if postgres else f"json_extract(event, '$.{name}')"
            identifier = "event->'value'->>'id'" if postgres else "json_extract(event, '$.value.id')"
            cumulative = f"{field('type')} = 'CUSTOM' AND {field('name')} = 'agent_activity' AND {identifier} IS NOT NULL"
            placeholders = ','.join(f'${index + 1}' if postgres else '?' for index in range(len(missing)))
            # Rank only IDs, keeping large JSON payloads out of the window sorter.
            sql = f'''WITH ranked AS (
                SELECT id, CASE WHEN {cumulative} THEN
                    ROW_NUMBER() OVER (PARTITION BY message_id, {field('name')}, {identifier} ORDER BY seq DESC)
                    ELSE 1 END AS position
                FROM creation_agent_events WHERE message_id IN ({placeholders})
            ) SELECT e.message_id, e.event FROM creation_agent_events e
              JOIN ranked r ON e.id = r.id WHERE r.position = 1 ORDER BY e.message_id, e.seq'''
            rows = await db.execute_query_dict(sql, list(missing))
            for identifier in missing:
                loaded[identifier] = []
            for row in rows:
                event = row['event']
                loaded[row['message_id']].append(json.loads(event) if isinstance(event, str) else event)
            cached_rows = []
            for identifier, version in missing.items():
                self.projections[(db, identifier)] = (version, loaded[identifier])
                message = next(message for message in messages if message.id == identifier)
                cached_rows.append(AgentOperation(task_id=message.task_id, key=f'view:events:{identifier}',
                    state='completed', result={'projection_version': 1, 'seq': version, 'events': loaded[identifier]}))
            await AgentOperation.bulk_create(cached_rows, on_conflict=('task_id', 'key'), update_fields=('state', 'result'))
        while len(self.projections) > 32:
            self.projections.popitem(last=False)
        return loaded

    async def last(self, message: AgentMessage) -> dict | None:
        events = await AgentEvent.filter(message_id=message.id).order_by('-seq').limit(1).values_list('event', flat=True)
        if events:
            return events[0]
        legacy = list(message.events or [])
        return legacy[-1] if legacy else None


agent_event_log = AgentEventLog()
