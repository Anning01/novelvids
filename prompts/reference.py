"""Recognize historical reference-sheet formats; stored prompts remain authoritative."""


CHARACTER_TURNAROUND = "character_turnaround"
GROUP_PORTRAIT = "group_portrait"
REFERENCE_OUTPUT_GUARD_ZH = "禁止生成任何文字、标签、Logo 或水印。"
REFERENCE_OUTPUT_GUARD_EN = "Do not generate text, labels, logos, or watermarks."


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
