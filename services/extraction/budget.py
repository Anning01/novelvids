"""Deterministic character budgets for prepared extraction messages."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudgetReport:
    message_characters: tuple[int, ...]
    total_characters: int


class ContextBudgetExceededError(ValueError):
    """Raised when configured extraction context capacity is exceeded."""


class ContextBudgetPolicy:
    """Validate prepared messages against an explicitly configured limit."""

    def __init__(self, max_context_characters: int | None):
        if max_context_characters is not None and max_context_characters < 1:
            raise ValueError("上下文字符上限必须大于 0")
        self.max_context_characters = max_context_characters

    def validate(
        self,
        messages: list[dict[str, str]],
        *,
        asset_count: int,
        chapter_characters: int,
    ) -> ContextBudgetReport:
        message_characters = tuple(len(message["content"]) for message in messages)
        total_characters = sum(message_characters)
        if (
            self.max_context_characters is not None
            and total_characters > self.max_context_characters
        ):
            raise ContextBudgetExceededError(
                "资产上下文超限："
                f"资产 {asset_count} 个，章节 {chapter_characters} 字符，"
                f"请求 {total_characters} 字符，"
                f"配置上限 {self.max_context_characters} 字符"
            )
        return ContextBudgetReport(
            message_characters=message_characters,
            total_characters=total_characters,
        )
