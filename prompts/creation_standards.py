"""Shared visual contracts; retrieval is type-specific, rendering has no side effects."""

import re
import json

from prompts.labels import prompt_label
from prompts.reference import CHARACTER_TURNAROUND
from prompts.storyboard_strategies import StoryboardStrategyPrompt


ASSET_PROMPT_KINDS = {1: "person", 2: "scene", 3: "item"}


def render_asset_design(description, visual_fields, kind, snapshot, language, aspect_ratio):
    specification = json.loads(snapshot.contents.get('asset_contract', '{}')).get(language, {}).get(kind)
    details = description.strip()
    if specification:
        task = specification['task'].format(aspect_ratio=aspect_ratio)
        if details.startswith(task or specification['heading']):
            return details
    preferred_fields = specification['fields'] if specification else []
    fields = [*preferred_fields, *(field for field in visual_fields if field not in preferred_fields)]
    field_lines = '\n'.join(f'**{field}**：{visual_fields[field].strip()}' for field in fields if visual_fields.get(field, '').strip())
    details = '\n\n'.join(part for part in (details, field_lines) if part)
    if not details or not specification:
        return details
    return '\n\n'.join(part for part in (task, specification['heading'], details, specification.get('suffix', '')) if part)


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
    from prompts.skill_pack import SkillSnapshot, snapshot_skills, instructions

    snapshot = SkillSnapshot.model_validate(snapshot_skills())
    return {
        "kind": kind, "language": language, "aspect_ratio": aspect_ratio,
        "reference_layout": layout, "required_fields": [],
        "writing_rules": instructions(snapshot, language, "storyboard" if kind == "storyboard" else "image"),
        "revision": snapshot.revision,
    }


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
