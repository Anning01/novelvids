"""Storyboard strategy registry and runtime factory."""

from collections.abc import Iterable

from prompts.storyboard_strategies import (
    CINEMATIC_STORYBOARD_STRATEGY,
    STORYBOARD_STRATEGY_PROMPTS,
    StoryboardStrategyPrompt,
)


class StoryboardStrategyFactory:
    """Resolve persisted keys, public names and legacy aliases consistently."""

    def __init__(
        self,
        strategies: Iterable[StoryboardStrategyPrompt],
        *,
        default_key: str,
    ) -> None:
        registered = tuple(strategies)
        if not registered:
            raise ValueError("至少需要注册一个分镜策略")
        self._strategies = registered
        default = next(
            (strategy for strategy in registered if strategy.key == default_key),
            None,
        )
        if default is None:
            raise ValueError(f"默认分镜策略未注册：{default_key}")
        self._default = default
        self._lookup: dict[str, StoryboardStrategyPrompt] = {}
        for strategy in registered:
            for value in (strategy.key, strategy.name, *strategy.aliases):
                normalized = self._normalize(value)
                existing = self._lookup.get(normalized)
                if existing is not None and existing.key != strategy.key:
                    raise ValueError(f"分镜策略标识重复：{value}")
                self._lookup[normalized] = strategy

    @staticmethod
    def _normalize(value: object) -> str:
        return str(value or "").strip().casefold()

    @property
    def default(self) -> StoryboardStrategyPrompt:
        return self._default

    def resolve(self, value: object = None) -> StoryboardStrategyPrompt:
        """Resolve a strategy, falling back safely for blank or legacy data."""
        if isinstance(value, StoryboardStrategyPrompt):
            return value
        return self._lookup.get(self._normalize(value), self.default)

    def list(self) -> tuple[StoryboardStrategyPrompt, ...]:
        return self._strategies


storyboard_strategy_factory = StoryboardStrategyFactory(
    STORYBOARD_STRATEGY_PROMPTS,
    default_key=CINEMATIC_STORYBOARD_STRATEGY.key,
)
