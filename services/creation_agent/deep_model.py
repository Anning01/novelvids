"""LangChain model interface over the application's existing authorized usage boundary."""

import json
import math
from contextvars import ContextVar
from collections.abc import AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage, message_chunk_to_message
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field
from pydantic_ai.messages import (
    ModelRequest, ModelResponse, PartStartEvent, PartDeltaEvent, SystemPromptPart,
    RetryPromptPart, TextPart, TextPartDelta, ToolCallPart, ToolCallPartDelta, ToolReturnPart, UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition

from services.creation_agent.model_boundary import RecordedAgentModel


_internal_call = ContextVar('deep_agent_internal_call', default=False)

def internal_call(config):
    metadata = (config or {}).get('metadata', {})
    return bool(metadata.get('lc_internal_call') or metadata.get('lc_source') == 'summarization')

def native_messages(messages):
    result = []
    for message in messages:
        if isinstance(message, SystemMessage):
            result.append(ModelRequest(parts=[SystemPromptPart(message.text)]))
        elif isinstance(message, HumanMessage):
            result.append(ModelRequest(parts=[UserPromptPart(message.text)]))
        elif isinstance(message, AIMessage):
            parts = [TextPart(message.text)] if message.text else []
            parts.extend(ToolCallPart(call['name'], call['args'], call['id']) for call in message.tool_calls)
            if parts:
                result.append(ModelResponse(parts=parts))
        elif isinstance(message, ToolMessage):
            part = (RetryPromptPart(content=message.content, tool_name=message.name, tool_call_id=message.tool_call_id)
                    if message.status == 'error' else ToolReturnPart(tool_name=message.name or '', content=message.content, tool_call_id=message.tool_call_id))
            result.append(ModelRequest(parts=[part]))
    return result


def request_parameters(tools):
    functions = [convert_to_openai_tool(tool)['function'] for tool in tools]
    return ModelRequestParameters(function_tools=[ToolDefinition(
        name=tool['name'], description=tool.get('description', ''), parameters_json_schema=tool.get('parameters', {}),
    ) for tool in functions], allow_text_output=True)


def working_context_tokens(messages, *, tools=None, token_budget, character_limit):
    """Map both configured budgets onto the SDK counter; the SDK still chooses compaction."""
    tokens = count_tokens_approximately(messages, tools=tools)
    if character_limit is None:
        return tokens
    from services.creation_agent.context_budget import wire_size
    characters = wire_size(native_messages(messages), request_parameters(tools or []))['total_characters']
    return max(tokens, math.ceil(characters * token_budget / character_limit))


class RecordedChatModel(BaseChatModel):
    """Delegate HTTP, authorization, auditing and token accounting without another model client."""

    recorded: RecordedAgentModel = Field(exclude=True, repr=False)
    settings: dict = Field(default_factory=dict)
    profile: dict = Field(default_factory=dict)

    @property
    def _llm_type(self):
        return 'novelvids-recorded'

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        token = _internal_call.set(internal_call(config))
        try:
            return await super().ainvoke(input, config, **kwargs)
        finally:
            _internal_call.reset(token)

    async def astream(self, input, config=None, **kwargs):
        token = _internal_call.set(internal_call(config))
        try:
            async for chunk in super().astream(input, config, **kwargs):
                yield chunk
        finally:
            _internal_call.reset(token)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError('Creation agents use the asynchronous model boundary')

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        combined = None
        async for chunk in self._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            combined = chunk.message if combined is None else combined + chunk.message
        return ChatResult(generations=[ChatGeneration(message=message_chunk_to_message(combined))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs) -> AsyncIterator[ChatGenerationChunk]:
        parameters = request_parameters(kwargs.get('tools', []))
        previous_phase = self.recorded.phase
        metadata = getattr(run_manager, 'metadata', None) or {}
        internal = _internal_call.get() or bool(metadata.get('lc_internal_call') or metadata.get('lc_source') == 'summarization')
        if internal:
            self.recorded.phase = 'summary'
            self.recorded.budget.compactions += 1
            if self.recorded.budget.on_compact:
                await self.recorded.budget.on_compact()
        settings = dict(self.settings)
        if internal:
            settings['max_tokens'] = min(self.recorded.budget.limits.summary_output_tokens,
                settings.get('max_tokens') or self.recorded.budget.limits.summary_output_tokens)
        try:
            async with self.recorded.request_stream(native_messages(messages), settings, parameters) as response:
                async for event in response:
                    chunk = None
                    if isinstance(event, PartStartEvent):
                        if isinstance(event.part, TextPart):
                            chunk = AIMessageChunk(content=event.part.content)
                        elif isinstance(event.part, ToolCallPart):
                            chunk = AIMessageChunk(content='', tool_call_chunks=[{
                                'name': event.part.tool_name, 'args': event.part.args if isinstance(event.part.args, str) else json.dumps(event.part.args) if event.part.args is not None else '',
                                'id': event.part.tool_call_id, 'index': event.index,
                            }])
                    elif isinstance(event, PartDeltaEvent):
                        if isinstance(event.delta, TextPartDelta):
                            chunk = AIMessageChunk(content=event.delta.content_delta)
                        elif isinstance(event.delta, ToolCallPartDelta):
                            args = event.delta.args_delta
                            chunk = AIMessageChunk(content='', tool_call_chunks=[{
                                'name': event.delta.tool_name_delta, 'args': json.dumps(args) if isinstance(args, dict) else args,
                                'id': event.delta.tool_call_id, 'index': event.index,
                            }])
                    # ThinkingPart and encrypted/provider reasoning are never public message content.
                    if chunk is not None:
                        yield ChatGenerationChunk(message=chunk)
                usage = response.usage()
                yield ChatGenerationChunk(message=AIMessageChunk(content='', usage_metadata={
                    'input_tokens': usage.input_tokens, 'output_tokens': usage.output_tokens,
                    'total_tokens': usage.input_tokens + usage.output_tokens,
                }, response_metadata={'finish_reason': response.finish_reason, 'model_provider': self._llm_type}))
        finally:
            self.recorded.phase = previous_phase
