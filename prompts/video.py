"""Pure prompt renderers for video generation continuity instructions."""

from __future__ import annotations

import re
import json
from prompts.skill_pack import render_voice_bindings
from prompts.labels import prompt_label


LAST_FRAME_CONTINUITY_TITLE = "【首帧衔接】"
_LAST_FRAME_CONTINUITY_SECTION = re.compile(
    rf'\A(?:(?:{re.escape(LAST_FRAME_CONTINUITY_TITLE)}|\[First-frame continuity\])\n[^\n]*|\{{"first_frame_reference": [^\n]*\}})(?:\n+|\Z)'
)


def render_last_frame_continuity_instruction(
    reference_mention: str, language: str = "zh"
) -> str:
    """Render the explicit first-frame purpose for an injected tail-frame image."""
    mention = reference_mention.strip()
    if not mention:
        return ""
    return f"{prompt_label(LAST_FRAME_CONTINUITY_TITLE, language)}\n{prompt_label('首帧参考：', language)}{mention}"


def normalize_last_frame_continuity_prompt(prompt: str, language: str = 'zh') -> str:
    """Render old protocol prefixes for submission without changing saved content."""
    first, _, _ = prompt.partition('\n')
    if not first.startswith('{"first_frame_reference":'):
        return prompt
    try:
        reference = json.loads(first).get('first_frame_reference')
    except (ValueError, AttributeError):
        return prompt
    return inject_last_frame_continuity_prompt(prompt, reference, language) if isinstance(reference, str) else prompt


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
    return render_voice_bindings(bindings)
