"""Narrative chunking policy for bounded storyboard generation calls."""

import re


DEFAULT_NARRATIVE_CHUNK_CHARACTERS = 6000
MIN_NARRATIVE_CHUNK_CHARACTERS = 600
CONTEXT_RESPONSE_RESERVE_CHARACTERS = 1200

_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\n])")


class StoryboardContextLimitError(ValueError):
    """Raised when configured context cannot hold rules and a useful narrative chunk."""


class NarrativeChunker:
    """Split long prose on semantic boundaries without carrying chat history forward."""

    def __init__(self, max_characters: int) -> None:
        if max_characters < MIN_NARRATIVE_CHUNK_CHARACTERS:
            raise ValueError(
                f"max_characters 不能小于 {MIN_NARRATIVE_CHUNK_CHARACTERS}"
            )
        self.max_characters = max_characters

    @classmethod
    def for_context_limit(
        cls,
        max_context_characters: int | None,
        fixed_message_characters: int,
    ) -> "NarrativeChunker":
        if max_context_characters is None:
            return cls(DEFAULT_NARRATIVE_CHUNK_CHARACTERS)

        available = (
            max_context_characters
            - fixed_message_characters
            - CONTEXT_RESPONSE_RESERVE_CHARACTERS
        )
        if available < MIN_NARRATIVE_CHUNK_CHARACTERS:
            raise StoryboardContextLimitError(
                "模型 max_context_characters 配置过小，无法容纳分镜规则、资产事实"
                f"和至少 {MIN_NARRATIVE_CHUNK_CHARACTERS} 字的小说片段"
            )
        return cls(min(DEFAULT_NARRATIVE_CHUNK_CHARACTERS, available))

    def split(self, text: str) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return [""]

        units = [unit for unit in _SENTENCE_BOUNDARY.split(normalized) if unit]
        chunks: list[str] = []
        current = ""
        for unit in units:
            for piece in self._split_oversized_unit(unit):
                if current and len(current) + len(piece) > self.max_characters:
                    chunks.append(current.strip())
                    current = ""
                current += piece
        if current.strip():
            chunks.append(current.strip())
        return chunks or [""]

    def split_for_retry(self, text: str) -> list[str]:
        """Halve a truncated batch while retaining sentence boundaries when possible."""
        retry_limit = max(MIN_NARRATIVE_CHUNK_CHARACTERS, len(text) // 2)
        if retry_limit >= len(text):
            return [text]
        return NarrativeChunker(retry_limit).split(text)

    def _split_oversized_unit(self, unit: str) -> list[str]:
        return [
            unit[index : index + self.max_characters]
            for index in range(0, len(unit), self.max_characters)
        ]
