"""Pure renderers for default asset image prompts stored in the database."""

from utils.prompt_language import normalize_prompt_language
from prompts.catalog import template, text


CHARACTER_TURNAROUND = "character_turnaround"
GROUP_PORTRAIT = "group_portrait"
REFERENCE_OUTPUT_GUARD_ZH = text("reference_output_guard", "zh")
REFERENCE_OUTPUT_GUARD_EN = text("reference_output_guard", "en")

SINGLE_CHARACTER_PROMPT_PREFIX_ZH = template(
    "reference_character_legacy_prefix.md", "zh"
)

SCENE_PROMPT_PREFIX_ZH = template("reference_scene_legacy_prefix.md", "zh")

REFERENCE_PROMPT_MARKERS_BY_KIND = {
    "person": (
        "任务：完成角色的上半身正面平视特写",
        "任务：生成同一组角色的群像关系参考图",
        "Task: Create an upper-body, front-facing, eye-level close-up",
        "Task: Create an ensemble character relationship reference image",
    ),
    "scene": (
        "生成四宫格画面，展示同一个场景",
        "Create a four-panel environment reference sheet",
    ),
    "item": ("【道具描述】", "[Prop description]"),
}
COMPLETE_REFERENCE_PROMPT_MARKERS = tuple(
    marker
    for markers in REFERENCE_PROMPT_MARKERS_BY_KIND.values()
    for marker in markers
)


def is_complete_reference_prompt(value: str) -> bool:
    """Return whether a value already contains an explicit image task."""
    text = value.strip()
    return any(text.startswith(marker) for marker in COMPLETE_REFERENCE_PROMPT_MARKERS)


def render_default_asset_prompt(
    *,
    asset_type: str,
    visual_traits: str,
    prompt_language: str = "en",
    aspect_ratio: str = "16:9",
    reference_layout: str = CHARACTER_TURNAROUND,
) -> str:
    """Render the editable default prompt that will be persisted with an asset.

    This renderer is intentionally used before persistence. Image generation must
    submit the stored prompt verbatim so a user's later edits remain authoritative.
    """
    details = visual_traits.strip()
    if not details or is_complete_reference_prompt(details):
        return details

    language = normalize_prompt_language(prompt_language)
    kind = asset_type.strip().lower()
    ratio = aspect_ratio.strip() or "16:9"
    layout = reference_layout.strip().lower()

    if kind == "person" and layout in {
        "group",
        "ensemble",
        "group_portrait",
        "group-portrait",
    }:
        return details
    names = {
        "person": "reference_character.md",
        "scene": "reference_scene.md",
        "item": "reference_item.md",
        "object": "reference_item.md",
        "prop": "reference_item.md",
    }
    return template(names.get(kind, "reference_other.md"), language).format(
        details=details, ratio=ratio, output_guard=text("reference_output_guard", language)
    )
