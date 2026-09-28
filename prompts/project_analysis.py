"""Pure, locale-specific story analysis and cover renderers."""

from prompts.catalog import template, text
from prompts.extraction import visual_rules

ANALYSIS_SYSTEM_PROMPT = template("analysis_system.md", "zh")


def render_analysis_messages(
    *, name: str, chapter_count: int, material: str, prompt_language: str
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": template("analysis_system.md", prompt_language).format(
                prompt_language_name=text("language_name", prompt_language),
                single_character_visual_rules=visual_rules("person", prompt_language),
            ),
        },
        {
            "role": "user",
            "content": text(
                "analysis_user",
                prompt_language,
                name=name,
                chapter_count=chapter_count,
                material=material,
            ),
        },
    ]


def render_cover_prompt(
    *, name: str, book_types: list[str], story_outline: str, prompt_language: str = "en"
) -> str:
    return template("cover.md", prompt_language).format(
        name=name, genres=", ".join(book_types), story_outline=story_outline
    )
