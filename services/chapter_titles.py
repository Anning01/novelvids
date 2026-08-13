"""Chapter title normalization shared by ingestion and prompt preparation."""

from __future__ import annotations

import re


_CHAPTER_ORDINAL_PREFIX = re.compile(
    r"^\s*第\s*(?:\d+|[零〇一二三四五六七八九十百千万亿两]+)\s*"
    r"[章回节集卷部]\s*(?:[·•:：、.．\-—_]\s*)?"
)


def strip_chapter_ordinal(value: str | None) -> str:
    """Return a semantic chapter title without a leading ordinal marker."""
    title = (value or "").strip()
    return _CHAPTER_ORDINAL_PREFIX.sub("", title, count=1).strip()


def normalize_chapter_title(
    value: str | None,
    *,
    fallback: str = "未命名",
) -> str:
    """Normalize a stored chapter name while guaranteeing a non-empty value."""
    title = strip_chapter_ordinal(value)
    if title:
        return title
    normalized_fallback = strip_chapter_ordinal(fallback)
    return normalized_fallback or "未命名"
