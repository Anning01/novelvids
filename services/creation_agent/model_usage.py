"""Preserve standard Chat Completions totals across usage-library versions."""

import httpx
from dataclasses import replace

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIStreamedResponse, OpenAIResponsesModel, OpenAIResponsesStreamedResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage
from pydantic_ai.messages import PartStartEvent, PartDeltaEvent, ThinkingPart, ThinkingPartDelta
from services.llm.usage import completion_cache_usage


def preserve_responses_usage(mapped, raw):
    if raw is not None:
        mapped.input_tokens = raw.input_tokens
        mapped.output_tokens = raw.output_tokens
        if raw.input_tokens_details is not None:
            mapped.cache_read_tokens = raw.input_tokens_details.cached_tokens
            mapped.details['cache_usage_reported'] = 1
    return mapped


class UsagePreservingResponsesStream(OpenAIResponsesStreamedResponse):
    def _map_usage(self, response):
        return preserve_responses_usage(super()._map_usage(response), response.usage)

    async def _get_event_iterator(self):
        async for event in super()._get_event_iterator():
            # The SDK stores emitted reasoning_text separately from summaries.
            # Project its plaintext for live display without changing native history.
            if isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart) and not event.part.content:
                text = ''.join((event.part.provider_details or {}).get('raw_content') or [])
                if text:
                    event = replace(event, part=replace(event.part, content=text))
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta) and not event.delta.content_delta:
                details = event.delta.provider_details
                details = details(None) if callable(details) else details
                text = ''.join((details or {}).get('raw_content') or [])
                if text:
                    event = replace(event, delta=replace(event.delta, content_delta=text))
            yield event


class UsagePreservingResponsesModel(OpenAIResponsesModel):
    def _process_response(self, response, model_settings, model_request_parameters):
        result = super()._process_response(response, model_settings, model_request_parameters)
        preserve_responses_usage(result.usage, response.usage)
        return result

    async def _process_streamed_response(self, response, model_settings, model_request_parameters):
        from dataclasses import fields
        stream = await super()._process_streamed_response(response, model_settings, model_request_parameters)
        return UsagePreservingResponsesStream(**{field.name: getattr(stream, field.name)
                                                for field in fields(stream) if field.init})


def preserve_chat_usage(mapped: RequestUsage, raw: CompletionUsage | None) -> RequestUsage:
    # genai-prices can emit fields absent from this Pydantic AI version (e.g.
    # output_reasoning_tokens), causing its extractor to return zero totals.
    # Standard provider totals remain authoritative; reasoning is already part
    # of completion_tokens and must not be charged a second time.
    if raw is not None:
        mapped.input_tokens = raw.prompt_tokens
        mapped.output_tokens = raw.completion_tokens
        cache = completion_cache_usage(raw)
        if cache:
            mapped.cache_read_tokens = cache['cache_read_tokens']
            mapped.details['cache_usage_reported'] = 1
        elif mapped.cache_read_tokens:
            mapped.details['cache_usage_reported'] = 1
    return mapped


class StrictUsagePreservingStreamedResponse(OpenAIStreamedResponse):
    def _map_usage(self, response: ChatCompletionChunk) -> RequestUsage:
        return preserve_chat_usage(super()._map_usage(response), response.usage)


class UsagePreservingStreamedResponse(StrictUsagePreservingStreamedResponse):
    async def _get_event_iterator(self):
        try:
            async for event in super()._get_event_iterator():
                yield event
        except httpx.RemoteProtocolError:
            # A provider finish marker confirms the content ended; a missing HTTP
            # trailer must not discard it. Schema/content validation still runs.
            if self.finish_reason not in {'stop', 'tool_call'}:
                raise
            self.provider_details = {**(self.provider_details or {}), 'stream_transport_interrupted': True}


class UsagePreservingChatModel(OpenAIChatModel):
    """Use the SDK's documented response hooks without replacing its tool loop."""

    strict_streaming = False

    async def _map_video_url_item(self, item):
        return {"type": "video_url", "video_url": {"url": item.url, **(item.vendor_metadata or {})}}

    async def _map_binary_content_item(self, item):
        if item.media_type.startswith("video/"):
            # Preserve the existing OpenAI-compatible video-input contract.
            metadata = item.vendor_metadata or {}
            video = {"url": item.data_uri}
            if "fps" in metadata:
                video["fps"] = metadata["fps"]
            return {"type": "video_url", "video_url": video}
        return await super()._map_binary_content_item(item)

    def prepare_request(self, model_settings: ModelSettings | None, model_request_parameters: ModelRequestParameters):
        settings, parameters = super().prepare_request(model_settings, model_request_parameters)
        settings = dict(settings or {})
        # Match the existing services.llm Chat Completions contract. Pydantic AI
        # renames this to max_completion_tokens, which compatible endpoints can
        # silently ignore. Keep the cap under its original wire parameter.
        output_limit = settings.pop('max_tokens', None)
        if output_limit is not None:
            settings['extra_body'] = {**settings.get('extra_body', {}), 'max_tokens': output_limit}
        return settings, parameters

    @property
    def _streamed_response_cls(self) -> type[OpenAIStreamedResponse]:
        return StrictUsagePreservingStreamedResponse if self.strict_streaming else UsagePreservingStreamedResponse

    def _map_usage(self, response: ChatCompletion) -> RequestUsage:
        return preserve_chat_usage(super()._map_usage(response), response.usage)
