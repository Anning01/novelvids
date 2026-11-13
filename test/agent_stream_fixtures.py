"""Stream deterministic model replies through the SDK's real event loop."""

from contextlib import asynccontextmanager
import inspect
import json

from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel


def streaming_model(respond):
    reported_usage = None

    async def stream(messages, info):
        nonlocal reported_usage
        response = respond(messages, info)
        if inspect.isawaitable(response):
            response = await response
        reported_usage = response.usage
        for index, part in enumerate(response.parts):
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {index: DeltaToolCall(name=part.tool_name, tool_call_id=part.tool_call_id,
                    json_args=part.args if isinstance(part.args, str) else json.dumps(part.args))}
            else:
                raise AssertionError(f'Unsupported fixture part: {type(part).__name__}')
    class FixtureModel(FunctionModel):
        @asynccontextmanager
        async def request_stream(self, *args, **kwargs):
            async with super().request_stream(*args, **kwargs) as response:
                yield response
                if reported_usage and (reported_usage.input_tokens or reported_usage.output_tokens):
                    response._usage = reported_usage

    return FixtureModel(respond, stream_function=stream)


def completion_stream_response(payload):
    """Represent a synthetic Chat Completions response as actual SSE chunks."""
    import httpx

    chunks = []
    for choice in payload['choices']:
        delta = dict(choice['message'])
        if 'tool_calls' in delta:
            delta['tool_calls'] = [{**call, 'index': index} for index, call in enumerate(delta['tool_calls'])]
        chunks.append({'id': payload['id'], 'object': 'chat.completion.chunk',
                       'created': payload['created'], 'model': payload['model'],
                       'choices': [{'index': choice['index'], 'delta': delta,
                                    'finish_reason': choice['finish_reason']}]})
    chunks.append({'id': payload['id'], 'object': 'chat.completion.chunk',
                   'created': payload['created'], 'model': payload['model'],
                   'choices': [], 'usage': payload['usage']})
    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                          content=''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks) + 'data: [DONE]\n\n')
