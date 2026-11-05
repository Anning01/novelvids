"""Conditional introduction requirements, independent of storyboard strategy."""

import json
from collections.abc import Mapping, Sequence

from utils.prompt_language import normalize_prompt_language


def asset_introduction_requirement(entities, previously_seen: Sequence[str], language: str,
                                   descriptions: Mapping[str, str] | None = None) -> str:
    subjects = [
        {"nickname": entity.name, "description": (descriptions or {}).get(entity.name, entity.description)}
        for entity in entities if entity.name not in previously_seen
    ]
    if not subjects:
        return ""
    targets = json.dumps(subjects, ensure_ascii=False, separators=(",", ":"))
    if normalize_prompt_language(language) == "en":
        return (f"Introduce these subjects once on their first actual appearance in the entire story, "
                f"inferring a brief introduction from their nickname and description: {targets}. "
                "Choose how to present it; do not invent facts or treat spoken mentions as appearances. "
                "Introduction text, if used, is exempt from the no-subtitles rule; otherwise follow the original strategy.")
    return (f"以下人物、物品或场景在全剧首次实际出现时，根据昵称和描述推断并简短介绍一次：{targets}。"
            "介绍方式自行决定，不编造，口头提及不算出现；若使用介绍文字，仅该文字例外于无字幕限制，其余遵循原分镜策略。")
