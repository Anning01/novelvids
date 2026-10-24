"""Stable storyboard strategy prompt definitions.

This module only contains immutable prompt data. Runtime selection lives in the
storyboard service factory.
"""

from dataclasses import dataclass, replace
import json
from prompts.catalog import catalog, text
from prompts.skill_pack import read_skill


@dataclass(frozen=True, slots=True)
class StoryboardStrategyPrompt:
    """Prompt fragments and public metadata for one storyboard strategy."""

    key: str
    name: str
    description: str
    prohibitions: str
    generation_rules: str = ""
    aliases: tuple[str, ...] = ()


CINEMATIC_STORYBOARD_STRATEGY = StoryboardStrategyPrompt(
    key="cinematic",
    name=text("strategy_cinematic_name", "zh"),
    description=text("strategy_cinematic_description", "zh"),
    prohibitions=json.loads(read_skill("strategies"))["cinematic"]["restrictions"],
    aliases=tuple(catalog("strategies.json", "zh")["strategy_cinematic_aliases"]),
)


NARRATION_STORYBOARD_STRATEGY = StoryboardStrategyPrompt(
    key="narration",
    name=text("strategy_narration_name", "zh"),
    description=text("strategy_narration_description", "zh"),
    generation_rules=json.loads(read_skill("strategies"))["narration"]["rules"],
    prohibitions=json.loads(read_skill("strategies"))["narration"]["restrictions"],
    aliases=tuple(catalog("strategies.json", "zh")["strategy_narration_aliases"]),
)


STORYBOARD_STRATEGY_PROMPTS = (
    CINEMATIC_STORYBOARD_STRATEGY,
    NARRATION_STORYBOARD_STRATEGY,
)


def localized_strategy(
    strategy: StoryboardStrategyPrompt, language: str
) -> StoryboardStrategyPrompt:
    if strategy.key not in {item.key for item in STORYBOARD_STRATEGY_PROMPTS}:
        return strategy
    return replace(
        strategy,
        generation_rules=json.loads(read_skill("strategies"))[strategy.key]["rules"],
        prohibitions=json.loads(read_skill("strategies"))[strategy.key]["restrictions"],
    )
