"""Pure prompt renderers for video generation continuity instructions."""

from __future__ import annotations

import re


LAST_FRAME_CONTINUITY_TITLE = "【首帧衔接】"
_LAST_FRAME_CONTINUITY_SECTION = re.compile(
    rf"\A{re.escape(LAST_FRAME_CONTINUITY_TITLE)}\n[^\n]*(?:\n+|\Z)"
)


def render_last_frame_continuity_instruction(reference_mention: str) -> str:
    """Render the explicit first-frame purpose for an injected tail-frame image."""
    mention = reference_mention.strip()
    if not mention:
        return ""
    return (
        f"{LAST_FRAME_CONTINUITY_TITLE}\n"
        f"{mention} 作为本镜头首帧，以该画面的构图、人物位置、姿态、朝向、"
        "光线和环境状态为动作起点，再自然推进本镜头内容。"
    )


def inject_last_frame_continuity_prompt(prompt: str, reference_mention: str) -> str:
    """Prepend or replace the generated tail-frame continuity section idempotently."""
    instruction = render_last_frame_continuity_instruction(reference_mention)
    body = _LAST_FRAME_CONTINUITY_SECTION.sub("", (prompt or "").strip(), count=1).strip()
    return f"{instruction}\n\n{body}".strip() if instruction else body
