"""Asset instruction rendering from the single skill pack."""

from prompts.skill_pack import render_skill, template_text


def targeted_cast_instructions(language: str) -> str:
    return template_text("asset_templates", "targeted_cast_instructions", language)


def targeted_design_instructions(language: str) -> str:
    return template_text("asset_templates", "targeted_design_instructions", language)


def render_cast_instructions(language: str) -> str:
    return template_text("asset_templates", "render_cast_instructions", language)


def render_cast_scope(language: str, cast: dict, required_assets: tuple) -> str:
    import json
    rule = template_text("asset_templates", "render_cast_scope", language) + "\n"
    return rule + json.dumps({'chapter_cast': cast, 'required_asset_names': required_assets}, ensure_ascii=False)


def render_extraction_system(language: str) -> str:
    return render_skill("assets", language)


def render_asset_repair(language: str, accepted: dict, issues: list[str]) -> str:
    import json

    rule = template_text("asset_templates", "render_asset_repair", language) + "\n"
    return rule + json.dumps({'accepted_assets': accepted, 'issues_to_fix': issues}, ensure_ascii=False)
