"""Explicit animation requirements for GIF image output."""

from prompts.skill_pack import template_text
from utils.prompt_language import normalize_prompt_language


def render_gif_prompt(prompt: str, *, frame_count: int, frame_duration_ms: int, language: str) -> str:
    requirement = template_text("image_templates", "gif", normalize_prompt_language(language)).format(
        frame_count=frame_count, frame_duration_ms=frame_duration_ms,
    )
    return f"{prompt}\n\n{requirement}"
