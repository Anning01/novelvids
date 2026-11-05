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
