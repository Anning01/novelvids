"""Shared visual contracts; retrieval is type-specific, rendering has no side effects."""

import hashlib
import json
import re

from prompts.labels import prompt_label
from prompts.language import output_language_rule
from prompts.extraction import (
    GROUP_PORTRAIT_TRAIT_LABELS,
    PLACEHOLDER_TRAIT_VALUES,
    SINGLE_CHARACTER_TRAIT_LABELS,
)
from prompts.reference import (
    CHARACTER_TURNAROUND,
    GROUP_PORTRAIT,
    REFERENCE_PROMPT_MARKERS_BY_KIND,
    render_default_asset_prompt,
)
from prompts.storyboard import STORYBOARD_LANGUAGE_INSTRUCTIONS
from prompts.storyboard_strategies import StoryboardStrategyPrompt
from utils.prompt_language import normalize_prompt_language


ASSET_PROMPT_KINDS = {1: "person", 2: "scene", 3: "item"}
STORYBOARD_REQUIRED_SECTIONS = (
    "禁止项",
    "风格定调",
    "角色 / 道具 / 场景引用",
    "全局前置条件",
    "镜头描述",
    "转场方式",
    "特效规范",
)


def visual_contract(
    kind: str,
    *,
    language: str,
    aspect_ratio: str,
    layout: str = CHARACTER_TURNAROUND,
    strategy: StoryboardStrategyPrompt | None = None,
) -> dict:
    from prompts.catalog import template, text
    from prompts.extraction import visual_rules, trait_labels
    from prompts.storyboard_strategies import localized_strategy

    language = normalize_prompt_language(language)
    if kind == "storyboard":
        instructions = template("storyboard_system.md", language).format(
            language_instruction=STORYBOARD_LANGUAGE_INSTRUCTIONS[language]
            + "\n"
            + output_language_rule(language)
        )
        if strategy:
            localized = localized_strategy(strategy, language)
            instructions += (
                "\n" + localized.generation_rules + "\n" + localized.prohibitions
            )
        labels = [
            prompt_label("【" + label + "】", language)
            for label in STORYBOARD_REQUIRED_SECTIONS
        ]
        rendering = text("visual_rendering", language)
    else:
        instructions = visual_rules(
            "group" if kind == "person" and layout == GROUP_PORTRAIT else kind, language
        )
        labels = (
            list(trait_labels(layout == GROUP_PORTRAIT, language))
            if kind == "person"
            else []
        )
        rendering = render_default_asset_prompt(
            asset_type=kind,
            visual_traits=text("visual_placeholder", language),
            prompt_language=language,
            aspect_ratio=aspect_ratio,
            reference_layout=layout,
        )
    body = {
        "kind": kind,
        "language": language,
        "aspect_ratio": aspect_ratio,
        "reference_layout": layout,
        "required_fields": labels,
        "writing_rules": instructions,
        "rendering": rendering,
        "submission": text("visual_submission", language),
    }
    body["revision"] = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]
    return body


def validate_person_visual_traits(
    text: str, layout: str = CHARACTER_TURNAROUND
) -> None:
    labels = (
        GROUP_PORTRAIT_TRAIT_LABELS
        if layout == GROUP_PORTRAIT
        else SINGLE_CHARACTER_TRAIT_LABELS
    )
    from prompts.extraction import matching_trait_labels

    labels = matching_trait_labels(text, labels)
    positions = []
    # A short prose sentence mentioning all labels is not a fourteen-row design.
    for label in labels:
        pattern = (
            r"(?m)^[ \t]*(?:[-*][ \t]+)?\*{0,2}"
            + re.escape(label)
            + r"\*{0,2}[ \t]*[:：][ \t]*([^\n]*)"
        )
        matches = list(re.finditer(pattern, text))
        values = [match.group(1) for match in matches]
        if (
            len(values) != 1
            or not values[0].strip(" *_`。.;；,，")
            or values[0].strip(" *_`。.;；,，").casefold() in PLACEHOLDER_TRAIT_VALUES
        ):
            raise ValueError(
                f"人物视觉描述须包含{len(labels)}项字段；「{label}」必须出现一次且内容具体，请先读取 get_creation_prompt_rules 补齐规范"
            )
        positions.append(matches[0].start())
    if positions != sorted(positions):
        raise ValueError(f"人物视觉描述必须按规范顺序包含{len(labels)}项固定字段")


def validate_storyboard_sections(text: str, previous: str | None = None) -> None:
    required = [f"【{name}】" for name in STORYBOARD_REQUIRED_SECTIONS]
    if "[Restrictions]" in (previous if previous is not None else text):
        required = [prompt_label(label, "en") for label in required]
    # A legacy hand-written draft can be changed locally without pretending it
    # has a complete structured representation. Never delete existing sections.
    expected = (
        [label for label in required if label in previous]
        if previous is not None
        else required
    )
    missing = [label for label in expected if label not in text]
    if missing:
        raise ValueError(
            "分镜提示词缺少必要栏目："
            + "、".join(missing)
            + "；新增请提供完整 structure，编辑请保留已有内容"
        )
    if previous is None:
        section_pattern = "|".join(re.escape(label) for label in required)
        for label in required:
            content = re.split(section_pattern, text.split(label, 1)[1], maxsplit=1)[0]
            if not content.strip():
                raise ValueError(
                    f"分镜提示词必要栏目 {label} 不能为空，请提供完整 structure"
                )


def validate_reference_kind(text: str, kind: str) -> None:
    if any(
        text.strip().startswith(prefix)
        for other, prefixes in REFERENCE_PROMPT_MARKERS_BY_KIND.items()
        if other != kind
        for prefix in prefixes
    ):
        raise ValueError(
            "参考图模板与对象类型不符，请读取该对象的 get_creation_prompt_rules"
        )
