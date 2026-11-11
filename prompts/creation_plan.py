"""Pure instructions for step handoffs and bounded creative corrections."""

from prompts.skill_pack import template_text


def asset_request_instructions(language: str) -> str:
    return template_text("plan_templates", "asset_request_instructions", language)


def step_requirements(language: str) -> str:
    return template_text("plan_templates", "step_requirements", language)


def correction_instructions(language: str) -> str:
    return template_text("plan_templates", "correction_instructions", language)


def reading_reference_instructions(language: str) -> str:
    return template_text("plan_templates", "reading_reference_instructions", language)


def plan_reference_instructions(language: str) -> str:
    return template_text("plan_templates", "plan_reference_instructions", language)


def chapter_sections_instructions(sections: list[tuple[str, str]], language: str) -> str:
    heading = template_text("plan_templates", "chapter_sections", language)
    return heading + '\n\n' + '\n\n'.join(f'{index}. {label}\n{instruction}' for index, (label, instruction) in enumerate(sections, 1))


def resolved_storyboard_resources_instructions(language: str) -> str:
    return template_text("plan_templates", "resolved_storyboard_resources_instructions", language)
