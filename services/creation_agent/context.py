"""Bounded chapter projections shared by discovery and the current-run context."""

from models.chapter import Chapter


def chapter_context(chapter: Chapter | None, character_budget: int, offset: int | None = None) -> dict | None:
    if chapter is None:
        if offset is not None:
            raise ValueError('当前请求未选择章节，不能读取章节片段')
        return None
    content = chapter.content or ""
    total = len(content)
    if offset is not None:
        if offset < 0 or offset > total:
            raise ValueError('章节读取位置超出正文范围，请根据 content_characters 调整')
        end = min(total, offset + character_budget)
        return {"id": chapter.id, "number": chapter.number, "name": chapter.name,
                "content_excerpt": content[offset:end], "content_truncated": offset > 0 or end < total,
                "content_characters": total, "content_offset": offset,
                "content_next_offset": end if end < total else None}
    truncated = len(content) > character_budget
    if truncated:
        half = max(1, character_budget // 2)
        content = f"{content[:half]}\n[…章节中部未载入…]\n{content[-half:]}"
    return {"id": chapter.id, "number": chapter.number, "name": chapter.name,
            "content_excerpt": content, "content_truncated": truncated,
            "content_characters": total, "content_offset": 0,
                "content_next_offset": character_budget // 2 if truncated else None}
