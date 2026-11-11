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
