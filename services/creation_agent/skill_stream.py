"""Project SDK tool events onto the existing, payload-free activity timeline."""

from datetime import datetime, timezone
from contextvars import ContextVar
from uuid import uuid4
from time import monotonic

from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.ui.ag_ui import AGUIEventStream
from ag_ui.core import RunAgentInput

from models.creation_agent import AgentMessage
from services.creation_agent.event_log import agent_event_log
from services.task_signals import task_signals
from utils.messages import localized_message


def skill_activity_label(skill, language):
    return localized_message({
        'authorization': '理解生成要求', 'story': '分析故事', 'assets': '提取本章资产',
        'image': '准备图片提示词', 'storyboard': '生成分镜', 'remake': '分析参考视频',
        'video': '准备视频提示词', 'screenplay': '编写本集剧本',
        'planning_request': '梳理创作需求', 'creation_planning': '制定创作方案',
        'source_reading': '阅读原文素材', 'creative_check': '检查生成内容与创作要求',
        'structured': '整理创作内容',
    }.get(skill, '生成创作内容'), _language=language)


skill_event_sink = ContextVar('skill_event_sink', default=None)


async def forward_skill_event(event):
    sink = skill_event_sink.get()
    if sink is not None and event.get('type') == 'CUSTOM' and event.get('name') in {'agent_activity', 'agent_activity_delta'}:
        await sink(event)


class SkillRunActivity:
    def __init__(self, message: AgentMessage, owner_task_id: str, *, public_thinking=True):
        self.public_thinking = public_thinking
        self.message = message
        self.owner_task_id = owner_task_id
        self.pending: dict[str, dict] = {}
        self.thinking: dict | None = None
        self.thinking_count = 0
        self.run_id = uuid4().hex
        self.thinking_delta: list[str] = []
        self.last_thinking_flush = 0.0
        self.protocol = AGUIEventStream(run_input=RunAgentInput(
            thread_id=str(message.conversation_id), run_id=str(message.task_id),
            messages=[], tools=[], context=[], state={}, forwarded_props={}))

    async def publish(self, item: dict):
        event = {'type': 'CUSTOM', 'name': 'agent_activity', 'value': item,
                 'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000)}
        await self.publish_event(event)

    async def publish_event(self, event: dict):
        # Model lifecycle events share this journal, so obtain the current cursor.
        seq = await agent_event_log.start(self.message)
        await agent_event_log.append(self.message.id, [event], seq)
        await forward_skill_event(event)
        await task_signals.publish(self.owner_task_id)

    async def flush_thinking(self):
        if not self.thinking_delta or self.thinking is None:
            return
        delta = ''.join(self.thinking_delta)
        self.thinking_delta.clear()
        offset = len(self.thinking['detail'].encode('utf-16-le')) // 2
        self.thinking['detail'] += delta
        self.last_thinking_flush = monotonic()
        await self.publish_event({'type': 'CUSTOM', 'name': 'agent_activity_delta',
            'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
            'value': {key: value for key, value in self.thinking.items() if key != 'detail'} |
                     {'detail_delta': delta, 'detail_offset': offset}})

    async def __call__(self, _ctx, events):
        try:
            async for event in events:
                # Only the SDK's public thinking content; ordinary text, signatures
                # and encrypted reasoning never become a visible summary.
                if self.public_thinking:
                    async for public in self.protocol.handle_event(event):
                        if public.type in {'THINKING_TEXT_MESSAGE_START', 'THINKING_TEXT_MESSAGE_CONTENT',
                                           'THINKING_TEXT_MESSAGE_END'}:
                            if public.type == 'THINKING_TEXT_MESSAGE_START':
                                self.thinking_count += 1
                                self.thinking = {'id': f'model:{self.message.task_id}:thinking:{self.run_id}:{self.thinking_count}',
                                    'kind': 'thinking', 'label': '思考过程', 'detail': '', 'status': 'running',
                                    'started_at': datetime.now(timezone.utc).isoformat()}
                                self.last_thinking_flush = 0.0
                                await self.publish(dict(self.thinking))
                            elif self.thinking and public.type == 'THINKING_TEXT_MESSAGE_CONTENT':
                                self.thinking_delta.append(public.delta)
                                if monotonic() - self.last_thinking_flush >= .2:
                                    await self.flush_thinking()
                            elif self.thinking:
                                await self.flush_thinking()
                                self.thinking.update(status='completed', finished_at=datetime.now(timezone.utc).isoformat())
                                await self.publish(dict(self.thinking))
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
            await self.flush_thinking()
            if self.thinking and self.thinking['status'] == 'running':
                await self.publish({**self.thinking, 'status': 'failed',
                                    'finished_at': datetime.now(timezone.utc).isoformat()})
            # Cancellation and tool exceptions must not leave an active tool in replay.
            for item in self.pending.values():
                await self.publish({**item, 'status': 'failed',
                                    'finished_at': datetime.now(timezone.utc).isoformat()})
            self.pending.clear()
