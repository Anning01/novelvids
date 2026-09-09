"""Share current visual definitions between generation and prompt editing."""

import re

from prompts.reference import (
    REFERENCE_OUTPUT_GUARD_EN,
    REFERENCE_OUTPUT_GUARD_ZH,
    is_complete_reference_prompt,
)


def visual_entity_description(description: str | None, prompt: str | None) -> str:
    """Unwrap the repository's reference-sheet format, preserving custom text."""
    traits = (prompt or '').strip()
    if is_complete_reference_prompt(traits):
        match = re.search(r'(?:角色描述[：:]|场景描述[：:]|Character description:|Scene description:|【道具描述】|\[Prop description\])\s*', traits)
        if match:
            traits = traits[match.end():].strip()
            for guard in (REFERENCE_OUTPUT_GUARD_ZH, REFERENCE_OUTPUT_GUARD_EN):
                traits = traits.removesuffix(guard).strip()
    return '\n'.join(dict.fromkeys(value for value in ((description or '').strip(), traits) if value))
