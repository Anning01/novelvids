"""人物、场景、道具统一文本资产提取 Prompt。"""

from prompts.catalog import template, text, catalog

import re


SINGLE_CHARACTER_TRAIT_LABELS = (
    "时代基底",
    "国家/朝代",
    "人种",
    "类型基底",
    "脸型",
    "发型",
    "耳饰",
    "身材",
    "头身比",
    "上身着装",
    "下身着装",
    "鞋子",
    "性别",
    "年龄",
)

GROUP_PORTRAIT_TRAIT_LABELS = (
    "人物特征",
    "年龄段",
    "性别",
    "种族",
    "人数规模",
    "身材",
    "脸型",
    "眉毛",
    "眼镜",
    "鼻子",
    "嘴唇",
    "皮肤",
    "特殊标记",
    "发型",
    "服饰和道具",
)

PLACEHOLDER_TRAIT_VALUES = frozenset(
    {
        "无",
        "none",
        "无/none",
        "无法确认",
        "未知",
        "unknown",
        "未提及",
        "not mentioned",
        "无法辨识",
        "unidentifiable",
    }
)


SINGLE_CHARACTER_VISUAL_RULES = template("character_rules.md", "zh")


def ensure_ordered_trait_labels(
    value: str,
    labels: tuple[str, ...],
    contract_name: str,
) -> str:
    """Reject non-empty visual traits that do not honor the selected contract."""
    text = value.strip()
    if not text:
        return value
    labels = matching_trait_labels(text, labels)
    matches = [
        re.search(
            r"(?m)^[ \t]*(?:[-*][ \t]+)?\*{0,2}"
            + re.escape(label)
            + r"\*{0,2}[ \t]*[:：]",
            text,
        )
        for label in labels
    ]
    positions = [match.start() if match else -1 for match in matches]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise ValueError(f"{contract_name}必须按顺序包含{len(labels)}项固定字段")
    for index, (label, position) in enumerate(zip(labels, positions, strict=True)):
        end = positions[index + 1] if index + 1 < len(positions) else len(text)
        raw_value = text[matches[index].end() : end]
        normalized_value = re.sub(
            r"\s+",
            " ",
            raw_value.strip("*`_ \t\r\n:：-—。.;；,，"),
        ).casefold()
        if normalized_value in PLACEHOLDER_TRAIT_VALUES:
            raise ValueError(
                f"{contract_name}的固定字段不得使用占位值；缺失信息必须根据小说语境推断"
            )
    return value


GROUP_VISUAL_RULES = template("group_rules.md", "zh")

SCENE_VISUAL_RULES = template("scene_rules.md", "zh")

ITEM_VISUAL_RULES = template("item_rules.md", "zh")


# Extraction selection rules remain separate from reusable visual contracts.
ASSET_EXTRACTION_SYSTEM_PROMPT = (
    template("extraction_system.md", "zh")
    .replace("{group_visual_rules}", GROUP_VISUAL_RULES)
    .replace("{scene_visual_rules}", SCENE_VISUAL_RULES)
    .replace("{item_visual_rules}", ITEM_VISUAL_RULES)
)


def visual_rules(kind: str, language: str) -> str:
    names = {
        "person": "character_rules.md",
        "group": "group_rules.md",
        "scene": "scene_rules.md",
        "item": "item_rules.md",
    }
    return template(names[kind], language).format(
        prompt_language_name=text("language_name", language)
    )


def render_extraction_system(language: str) -> str:
    return template("extraction_system.md", language).format(
        prompt_language_name=text("language_name", language),
        single_character_visual_rules=visual_rules("person", language),
        group_visual_rules=visual_rules("group", language),
        scene_visual_rules=visual_rules("scene", language),
        item_visual_rules=visual_rules("item", language),
    )


def trait_labels(group: bool = False, language: str = "zh") -> tuple[str, ...]:
    return tuple(catalog("contracts.json", language)["group" if group else "single"])


def matching_trait_labels(value: str, labels: tuple[str, ...]) -> tuple[str, ...]:
    """Accept one complete locale contract, retaining historical Chinese designs."""
    group = tuple(labels) == GROUP_PORTRAIT_TRAIT_LABELS
    english = trait_labels(group, "en")
    if re.search(
        r"(?m)^[ \t]*(?:[-*][ \t]+)?\*{0,2}"
        + re.escape(english[0])
        + r"\*{0,2}[ \t]*:",
        value,
    ):
        return english
    return labels
