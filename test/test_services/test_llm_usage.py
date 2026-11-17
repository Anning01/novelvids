from types import SimpleNamespace
import pytest
from services.llm.usage import completion_usage, completion_cache_usage


def test_completion_usage_reads_openai_usage():
    completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46)
    )
    assert completion_usage(completion) == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }


def test_completion_usage_missing_usage_is_empty():
    assert completion_usage(SimpleNamespace()) == {}


@pytest.mark.parametrize('payload', [
    {'prompt_tokens_details': {'cached_tokens': 800}},
    {'prompt_cache_hit_tokens': 800},
])
def test_completion_cache_usage_preserves_standard_and_compatible_usage(payload):
    from openai.types import CompletionUsage
    from services.creation_agent.model_usage import preserve_chat_usage
    from pydantic_ai.usage import RequestUsage
    raw = CompletionUsage(prompt_tokens=1000, completion_tokens=20, total_tokens=1020, **payload)
    normal = completion_usage(SimpleNamespace(usage=raw))
    agent = preserve_chat_usage(RequestUsage(), raw)
    assert normal['cache_read_tokens'] == agent.cache_read_tokens == 800
    assert normal['cache_usage_reported'] == agent.details['cache_usage_reported'] == 1
    assert agent.input_tokens == 1000 and agent.output_tokens == 20


@pytest.mark.parametrize('cached,expected', [(-20, 0), (0, 0), (2000, 1000)])
def test_cache_usage_is_bounded_by_total_input(cached, expected):
    raw = SimpleNamespace(prompt_tokens=1000, completion_tokens=20, total_tokens=1020,
                          prompt_cache_hit_tokens=cached)
    assert completion_usage(SimpleNamespace(usage=raw))['cache_read_tokens'] == expected
