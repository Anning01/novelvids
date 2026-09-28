"""Pure prompt renderers for video generation continuity instructions."""

from __future__ import annotations

import re
from prompts.catalog import text


LAST_FRAME_CONTINUITY_TITLE = "【首帧衔接】"
_LAST_FRAME_CONTINUITY_SECTION = re.compile(
    rf"\A(?:{re.escape(LAST_FRAME_CONTINUITY_TITLE)}|\[First-frame continuity\])\n[^\n]*(?:\n+|\Z)"
)


def render_last_frame_continuity_instruction(
    reference_mention: str, language: str = "zh"
) -> str:
    """Render the explicit first-frame purpose for an injected tail-frame image."""
    mention = reference_mention.strip()
    if not mention:
        return ""
    return text("continuity", language, mention=mention)


def inject_last_frame_continuity_prompt(
    prompt: str, reference_mention: str, language: str = "zh"
) -> str:
    """Prepend or replace the generated tail-frame continuity section idempotently."""
    instruction = render_last_frame_continuity_instruction(reference_mention, language)
    body = _LAST_FRAME_CONTINUITY_SECTION.sub(
        "", (prompt or "").strip(), count=1
    ).strip()
    return f"{instruction}\n\n{body}".strip() if instruction else body


def render_voice_reference_instruction(bindings: list[dict], *, language: str) -> str:
    """Bindings use the final deduplicated audio order, starting at one."""
    lines = [text("voice_intro", language)] if bindings else []
    for binding in bindings:
        names = ", ".join(binding["subjects"])
        if binding["kind"] == "narrator":
            names = text("narrator", language)
        # Provider reference markers are protocol tokens, not prose.
        marker = f"[音频{binding['index']}]"
        lines.append(text("voice_line", language, names=names, marker=marker))
    lines.append(text("voice_rule", language))
    return "\n".join(lines)
