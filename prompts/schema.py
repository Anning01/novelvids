"""Structured-output protocol; creative language is controlled by Skills."""

import json
from prompts.skill_pack import read_skill


def json_instruction(schema: dict, language: str) -> str:
    return read_skill("structured") + "\nlanguage=" + language + "\n" + json.dumps(schema, ensure_ascii=False)
