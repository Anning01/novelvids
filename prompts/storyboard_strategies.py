"""Stable storyboard strategy prompt definitions.

This module only contains immutable prompt data. Runtime selection lives in the
storyboard service factory.
"""

from dataclasses import dataclass


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
    prohibitions="无字幕、无水印、无 LOGO、无 BGM，仅保留环境音效与人物台词。",
    aliases=("电影化叙事 1.5", "电影化叙事", "默认"),
)


NARRATION_STORYBOARD_STRATEGY = StoryboardStrategyPrompt(
    key="narration",
    name="旁白叙事",
    description=(
        "由统一旁白补充剧情背景与转折，并可使用人物内心 OS；旁白、内心 OS "
        "只出现在角色没有说话的时间段，人物对白仍忠于原文，全程无 BGM。"
    ),
    generation_rules="""### 3A. 当前分镜策略：旁白叙事
- 全章使用同一位稳定的第三人称旁白，负责压缩背景、连接转折、强化悬念或补充画面无法直接表达的信息；不得机械复述画面中已经清楚可见的动作。
- 可以使用人物内心 OS 揭示无法由外部表演充分表达的动机、判断和冲突，但不得把每段心理活动都改成 OS。
- `narration` 每项必须写成精确时间段：旁白使用 `0.0s-2.0s: 旁白（语气）：内容`；人物内心 OS 使用 `2.0s-3.5s: @{完整实体名}（内心 OS，语气）：内容`。
- 旁白或人物内心 OS 只能安排在没有人物对白的时间段，禁止与 `dialogue` 的任何时间段重叠；同一时间只能有一个可辨识的人声主体。
- `dialogue` 每项同样必须包含开始与结束时间、说话人物、语气和原文。旁白不是每个镜头必需；应保留必要的纯环境声和沉默。
- 所有旁白、内心 OS 和对白的时间段都必须位于当前镜头 `duration` 内，并为动作与环境音保留可感知空间。
- 不得添加 BGM。""",
    prohibitions="无字幕、无水印、无 LOGO、无 BGM，仅保留环境音效、人物台词、旁白与人物内心 OS。",
    aliases=("旁白版本", "旁白模式"),
)


STORYBOARD_STRATEGY_PROMPTS = (
    CINEMATIC_STORYBOARD_STRATEGY,
    NARRATION_STORYBOARD_STRATEGY,
)
