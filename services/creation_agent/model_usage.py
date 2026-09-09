"""Preserve standard Chat Completions totals across usage-library versions."""

from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIStreamedResponse
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage


def preserve_chat_usage(mapped: RequestUsage, raw: CompletionUsage | None) -> RequestUsage:
    # genai-prices can emit fields absent from this Pydantic AI version (e.g.
    # output_reasoning_tokens), causing its extractor to return zero totals.
    # Standard provider totals remain authoritative; reasoning is already part
    # of completion_tokens and must not be charged a second time.
    if raw is not None:
        mapped.input_tokens = raw.prompt_tokens
        mapped.output_tokens = raw.completion_tokens
        if raw.prompt_tokens_details is not None:
            mapped.cache_read_tokens = raw.prompt_tokens_details.cached_tokens or 0
    return mapped


class UsagePreservingStreamedResponse(OpenAIStreamedResponse):
    def _map_usage(self, response: ChatCompletionChunk) -> RequestUsage:
        return preserve_chat_usage(super()._map_usage(response), response.usage)


class UsagePreservingChatModel(OpenAIChatModel):
    """Use the SDK's documented response hooks without replacing its tool loop."""

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
        return UsagePreservingStreamedResponse

    def _map_usage(self, response: ChatCompletion) -> RequestUsage:
        return preserve_chat_usage(super()._map_usage(response), response.usage)
