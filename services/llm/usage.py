"""Read provider-reported cache hits without guessing from repeated text."""

from typing import Any


def completion_cache_usage(usage: Any) -> dict[str, int]:
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None)
    if cached is None:
        cached = getattr(usage, "prompt_cache_hit_tokens", None)
    if cached is None:
        return {}
    total = int(getattr(usage, "prompt_tokens", 0) or 0)
    return {"cache_read_tokens": min(total, max(0, int(cached))), "cache_usage_reported": 1}


def completion_usage(completion) -> dict[str, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        **completion_cache_usage(usage),
    }
