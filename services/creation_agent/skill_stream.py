"""Project SDK tool events onto the existing, payload-free activity timeline."""

from datetime import datetime, timezone

from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.ui.ag_ui import AGUIEventStream
from ag_ui.core import RunAgentInput

from models.creation_agent import AgentMessage
from services.creation_agent.event_log import agent_event_log
from services.task_signals import task_signals


class SkillRunActivity:
    def __init__(self, message: AgentMessage, owner_task_id: str):
        self.message = message
        self.owner_task_id = owner_task_id
        self.pending: dict[str, dict] = {}
        self.protocol = AGUIEventStream(run_input=RunAgentInput(
            thread_id=str(message.conversation_id), run_id=str(message.task_id),
            messages=[], tools=[], context=[], state={}, forwarded_props={}))

    async def publish(self, item: dict):
        event = {'type': 'CUSTOM', 'name': 'agent_activity', 'value': item,
                 'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000)}
        await self.publish_event(event)

    async def publish_event(self, event: dict):
        seq = await agent_event_log.start(self.message)
        await agent_event_log.append(self.message.id, [event], seq)
        await task_signals.publish(self.owner_task_id)

    async def __call__(self, _ctx, events):
        try:
            async for event in events:
                # Only the SDK's public thinking content; ordinary text, signatures
                # and encrypted reasoning never become a visible summary.
                async for public in self.protocol.handle_event(event):
                    if public.type in {'THINKING_TEXT_MESSAGE_START', 'THINKING_TEXT_MESSAGE_CONTENT',
                                       'THINKING_TEXT_MESSAGE_END'}:
                        await self.publish_event(public.model_dump(mode='json', by_alias=True, exclude_none=True))
                if isinstance(event, FunctionToolCallEvent):
                    item = {'id': f'tool:{self.message.task_id}:{event.part.tool_call_id}',
                            'kind': 'tool', 'label': '执行步骤', 'tool_name': event.part.tool_name,
                            'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat()}
                    self.pending[event.part.tool_call_id] = item
                    await self.publish(item)
                elif isinstance(event, FunctionToolResultEvent):
                    item = self.pending.pop(event.result.tool_call_id, None)
                    if item is not None:
                        await self.publish({**item,
                            'status': 'failed' if isinstance(event.result, RetryPromptPart) else 'completed',
                            'finished_at': datetime.now(timezone.utc).isoformat()})
        finally:
            # Cancellation and tool exceptions must not leave an active tool in replay.
            for item in self.pending.values():
                await self.publish({**item, 'status': 'failed',
                                    'finished_at': datetime.now(timezone.utc).isoformat()})
            self.pending.clear()
