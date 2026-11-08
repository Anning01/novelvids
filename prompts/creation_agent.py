"""Creation-agent fixed instructions and side-effect-free prompt fragments."""

from prompts.skill_pack import render_skill

from collections.abc import Sequence
import json
import re

from prompts.storyboard import StoryboardEntity
from prompts.labels import prompt_label


def render_creation_request(message: str, current_selection: dict | None = None, preflight: dict | None = None) -> str:
    """Keep server facts separate from the user's instruction and the stable system prefix."""
    payload = {"user_request": message}
    if current_selection is not None:
        payload["current_selection"] = current_selection
    if preflight is not None:
        payload['preflight_context'] = preflight
    return json.dumps(payload, ensure_ascii=False)


def render_creation_summary(previous: str, messages: list[dict]) -> str:
    return json.dumps(
        {"previous_summary": previous, "conversation_records": messages},
        ensure_ascii=False,
    )


def render_working_checkpoint(
    evidence: dict
) -> str:
    """Historical evidence stays user/tool data, never new system authority."""
    return json.dumps(
        {
            "working_checkpoint": evidence,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def without_prompt_definitions(prompt: str) -> str:
    """Replace renderer-owned definition sections on each edit, not user prose."""
    return re.sub(
        r"\n*(?:【当前请求资产定义】|\[Asset definitions for this request\])\s*\n.*?(?=\n(?:【|\[)|\Z)",
        "\n",
        prompt,
        flags=re.S,
    ).strip()


def render_prompt_definitions(
    prompt: str, entities: Sequence[StoryboardEntity], language: str = "zh"
) -> str:
    if not entities:
        return prompt
    definitions = "\n".join(
        f"@{{{entity.name}}}：{entity.description}" for entity in entities
    )
    return (
        f"{prompt}\n\n{prompt_label('【当前请求资产定义】', language)}\n{definitions}"
    )


def render_preserved_tracks(prompt: str, parameters: dict) -> str:
    """Carry authoritative voice tracks into a free-text edit of the visual prompt."""
    language = parameters.get("prompt_language", "zh")
    parts = [prompt]
    section_patterns = {
        "narration": re.compile(
            r"(?m)^\s*(?:【旁白(?:\s*/\s*内心\s*OS)?】|\[Narration / Inner monologue\]|(?:旁白|Narrator)\s*[：:])"
        ),
        "dialogue": re.compile(
            r"(?m)^\s*(?:【人物台词】|\[Character dialogue\]|(?:人物)?(?:台词|对白)\s*[：:])"
        ),
    }
    for key, label in (("narration", "旁白 / 内心 OS"), ("dialogue", "人物台词")):
        tracks = parameters.get(key)
        missing = (
            [
                track
                for track in tracks
                if isinstance(track, str) and track.strip() and track not in prompt
            ]
            if isinstance(tracks, list) and section_patterns[key].search(prompt) is None
            else []
        )
        if missing:
            parts.extend((prompt_label(f"【{label}】", language), *missing))
    sound = parameters.get("sound_design")
    has_sound_section = re.search(
        r"(?m)^\s*(?:【声音设计】|(?:环境音|同步声音|声音设计)\s*[：:])",
        prompt,
    )
    if (
        isinstance(sound, str)
        and sound.strip()
        and sound not in prompt
        and has_sound_section is None
    ):
        parts.extend((prompt_label("【声音设计】", language), sound))
    return "\n".join(parts)


TURN_LIMITED_NOTICE = (
    "本轮模型调用次数已到上限，工具已收起，本次请求不能再调用任何工具。"
    "请直接给出最终回复：用任务语言、以用户可见的对象名称说明已实际保存的修改、尚未完成的部分及原因。"
    "已保存的修改以回执为准，不要把未完成的操作说成已完成。"
)


def render_turn_limited_notice() -> str:
    """Fixed closing instruction for the request on which the tool loop is withdrawn."""
    return TURN_LIMITED_NOTICE


def render_creation_instructions(*, language: str, crud=False, turn_limited=False) -> str:
    rendered = render_skill("editing", language)
    if turn_limited:
        rendered += "\n" + render_turn_limited_notice()
    return rendered


def render_summary_instructions(language: str = "zh") -> str:
    return render_skill("summary", language)
