"""Stable storyboard strategy prompt definitions.

This module only contains immutable prompt data. Runtime selection lives in the
storyboard service factory.
"""

from dataclasses import dataclass, replace
from prompts.catalog import template, text


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
    name="电影感叙事",
    description=(
        "沿用当前电影化分镜规则，强调连续动作、景别变化与情绪转折，"
        "以电影感画面和人物表演推进剧情。"
    ),
    prohibitions=text("prohibitions_cinematic", "zh"),
    aliases=("电影化叙事 1.5", "电影化叙事", "默认"),
)


NARRATION_STORYBOARD_STRATEGY = StoryboardStrategyPrompt(
    key="narration",
    name="旁白叙事",
    description=(
        "由统一旁白补充剧情背景与转折，并可使用人物内心 OS；旁白、内心 OS "
        "只出现在角色没有说话的时间段，人物对白仍忠于原文，全程无 BGM。"
    ),
    generation_rules=template("strategy_narration.md", "zh"),
    prohibitions=text("prohibitions_narration", "zh"),
    aliases=("旁白版本", "旁白模式"),
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
        generation_rules=template(f"strategy_{strategy.key}.md", language),
        prohibitions=text(f"prohibitions_{strategy.key}", language),
    )
