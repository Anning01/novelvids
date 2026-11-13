"""Presentation rules for placing one attached sheet in the chosen draft."""
from prompts.skill_pack import read_skill
import json


def sheet_binding_rules(sheet, language):
    templates = json.loads(read_skill("storyboard_sheet_templates"))["en" if language == "en" else "zh"]
    generic = sheet.get("video_guidance") or templates["video"]
    registry = json.loads(read_skill("video_prompt_models"))
    bindings = templates.get("model_binding", {})
    return {
        "general": {"line": "{image} " + generic, "headings": ["【角色 / 道具 / 场景引用】", "[Character / Prop / Location references]"]},
        **{key: bindings[profile["skill"]] for key, profile in registry.items()
           if profile["skill"] in bindings},
    }


def model_image_format(model_type):
    profile = json.loads(read_skill("video_prompt_models")).get(model_type, {})
    binding = json.loads(read_skill("storyboard_sheet_templates"))["en"].get("model_binding", {}).get(profile.get("skill"), {})
    return binding.get("image_format", "[图{}]")


def blocking_rules(language):
    templates = json.loads(read_skill("storyboard_sheet_templates"))
    local = "en" if language == "en" else "zh"
    lines = json.loads(read_skill("blocking_prompt"))
    registry = json.loads(read_skill("video_prompt_models"))
    rules = {"general": {"line": lines[local], "headings": ["空间关系：", "Spatial relations:"]}}
    for model, profile in registry.items():
        skill = profile["skill"]
        locale = "en" if skill == "h3-prompt-writing" else local
        template = templates[locale]
        if skill in template["model_binding"]:
            rules[model] = {"line": lines[locale], "headings": template["model_binding"][skill]["headings"]}
    return rules


def bind_blocking(prompt, rule, marker):
    if marker in prompt:
        return prompt
    lines = prompt.splitlines()
    insert = next((i + 1 for i, line in enumerate(lines)
                   if any(line.strip().startswith(h) for h in rule["headings"])), len(lines))
    lines.insert(insert, rule["line"].replace("{image}", marker))
    return "\n".join(lines)
