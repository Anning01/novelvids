"""Model-facing instructions for bounded storyboard patches."""

import json

from prompts.skill_pack import template_text


def structural_repair(language, checkpoint):
    text = template_text("storyboard_templates", "structural_repair", language) + "\n"
    return text + json.dumps({**{key: checkpoint[key] for key in ('accepted_shots', 'pending', 'protocol_errors')},
        'repair_targets': {number: checkpoint['candidates'][number] for number in checkpoint['pending']}}, ensure_ascii=False)


def semantic_repair(language):
    return template_text("storyboard_templates", "semantic_repair", language)


def review_locations(language):
    return template_text("storyboard_templates", "review_locations", language)
