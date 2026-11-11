"""Optional Python Deep Agents host; the SDK owns the tool loop and checkpoint context."""

import json
from collections.abc import AsyncIterator
from uuid import uuid4

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage


class BusinessToolsOnly(AgentMiddleware):
    """Keep the host's tool allowlist authoritative, including hallucinated calls."""

    def __init__(self, names: set[str]):
        self.names = names

    async def awrap_model_call(self, request, handler):
        return await handler(request.override(tools=[tool for tool in request.tools if
            (tool.get('name') if isinstance(tool, dict) else tool.name) in self.names]))

    async def awrap_tool_call(self, request, handler):
        if request.tool_call['name'] not in self.names:
            return ToolMessage(content='Tool is not permitted', status='error',
                               tool_call_id=request.tool_call['id'])
        return await handler(request)


def create_runtime(*, model, tools, instructions, checkpointer, summarization=None):
    """Supply a per-user checkpointer and validated business tools at the Python boundary."""
    backend = StateBackend()
    middleware = [BusinessToolsOnly({'read_file', *(tool.name for tool in tools)})]
    if summarization is not None:
        middleware.append(SummarizationMiddleware(model=model, backend=backend, **summarization))
    return create_deep_agent(model=model, tools=tools, system_prompt=instructions,
        skills=['/skills/'], backend=backend, checkpointer=checkpointer, middleware=middleware)


async def public_events(graph, inputs: dict, *, thread_id: str, run_id: str) -> AsyncIterator[dict]:
    """Expose prose and execution lifecycle without exposing reasoning or write payloads."""
    config = {'configurable': {'thread_id': thread_id}, 'recursion_limit': 50}
    messages = {}
    yield {'type': 'RUN_STARTED', 'threadId': thread_id, 'runId': run_id}
    async for event in graph.astream_events(inputs, config=config, version='v2'):
        kind, identifier = event['event'], str(event['run_id'])
        metadata = event.get('metadata', {})
        if metadata.get('lc_internal_call') or metadata.get('lc_source') == 'summarization':
            continue
        if kind == 'on_chat_model_stream' and metadata.get('langgraph_node') == 'model':
            content = event['data']['chunk'].content
            texts = [content] if isinstance(content, str) else [
                block['text'] for block in content if isinstance(block, dict) and block.get('type') == 'text']
            for text in filter(None, texts):
                if identifier not in messages:
                    messages[identifier] = str(uuid4())
                    yield {'type': 'TEXT_MESSAGE_START', 'messageId': messages[identifier], 'role': 'assistant'}
                yield {'type': 'TEXT_MESSAGE_CONTENT', 'messageId': messages[identifier], 'delta': text}
        elif kind == 'on_chat_model_end' and identifier in messages:
            yield {'type': 'TEXT_MESSAGE_END', 'messageId': messages[identifier]}
        elif kind == 'on_tool_start':
            yield {'type': 'TOOL_CALL_START', 'toolCallId': identifier, 'toolCallName': event['name']}
            yield {'type': 'TOOL_CALL_END', 'toolCallId': identifier}
        elif kind == 'on_tool_end':
            failed = getattr(event['data'].get('output'), 'status', None) == 'error'
            yield {'type': 'TOOL_CALL_RESULT', 'toolCallId': identifier, 'messageId': str(uuid4()),
                   'role': 'tool', 'content': json.dumps({'status': 'failed' if failed else 'completed'})}
            yield {'type': 'CUSTOM', 'name': 'agent_activity', 'value': {
                'id': f'tool:{identifier}', 'kind': 'tool', 'tool_name': event['name'],
                'label': '执行步骤', 'status': 'failed' if failed else 'completed'}}
    yield {'type': 'RUN_FINISHED', 'threadId': thread_id, 'runId': run_id}
