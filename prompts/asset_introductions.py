"""Conditional introduction requirements, independent of storyboard strategy."""

import json
from collections.abc import Mapping, Sequence

from prompts.skill_pack import template_text
from utils.prompt_language import normalize_prompt_language


def asset_introduction_requirement(entities, previously_seen: Sequence[str], language: str,
                                   descriptions: Mapping[str, str] | None = None) -> str:
    seen_names = {name.partition('#')[0] for name in previously_seen}
    subjects = []
    for entity in entities:
        name = entity.name.partition('#')[0]
        if name not in seen_names:
            subjects.append({"nickname": name, "description": (descriptions or {}).get(name, entity.description)})
            seen_names.add(name)
    if not subjects:
        return ""
    targets = json.dumps(subjects, ensure_ascii=False, separators=(",", ":"))
    return template_text("storyboard_templates", "introduce", normalize_prompt_language(language)).format(targets=targets)
