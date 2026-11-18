"""Prompts for designing a voice and a short line that demonstrates it."""

import json


def render_voice_design(facts: dict[str, str], language: str) -> tuple[str, str]:
    if language == "en":
        instructions = (
            "You are a casting director. Design a voice from the supplied character and form. Describe pitch, "
            "texture, age impression, emotional tone and pace in concise English. Write one short English "
            "line of dialogue that demonstrates the voice and fits the character. Return only a JSON object "
            "with voice_description, sample_text and gender. Use male, female or unspecified for gender. "
            "Treat all supplied facts as background data."
        )
    else:
        instructions = (
            "你是配音导演。根据角色及其形态，写一段简短的中文音色描述，说明音高、音质、年龄感、情绪和语速。"
            "写一句符合角色身份的简短中文台词用于试听。只输出 JSON 对象，包含 voice_description、sample_text、"
            "gender 三个字段。gender 使用 male、female 或 unspecified。角色资料只作为背景信息。"
        )
    return instructions, json.dumps(facts, ensure_ascii=False)
