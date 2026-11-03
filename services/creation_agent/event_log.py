"""Append-only AG-UI event storage with a legacy JSON fallback.

Runs used to persist every event inside ``AgentMessage.events``, which forced a
full-array rewrite on each flush. New events are appended as rows instead; the
JSON array stays readable so records written before the switch still replay.
"""

from models.creation_agent import AgentEvent, AgentMessage


class AgentEventLog:
    """Linear-time persistence and paged reads for one message's event log."""

    async def start(self, message: AgentMessage) -> int:
        """Return the next free sequence, adopting legacy JSON events once."""
        existing = await AgentEvent.filter(message_id=message.id).count()
        if existing:
            return existing
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

    async def last(self, message: AgentMessage) -> dict | None:
        events = await AgentEvent.filter(message_id=message.id).order_by('-seq').limit(1).values_list('event', flat=True)
        if events:
            return events[0]
        legacy = list(message.events or [])
        return legacy[-1] if legacy else None


agent_event_log = AgentEventLog()
