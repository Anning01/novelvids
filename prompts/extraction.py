"""Asset instruction rendering from the single skill pack."""

from prompts.skill_pack import render_skill


def render_extraction_system(language: str) -> str:
    return render_skill("assets", language)
