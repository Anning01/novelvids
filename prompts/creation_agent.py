"""Creation-agent fixed instructions and side-effect-free prompt fragments."""

from prompts.catalog import template, text

from collections.abc import Sequence
import json
import re

from prompts.storyboard import StoryboardEntity
from prompts.labels import prompt_label


CREATION_AGENT_INSTRUCTIONS = template("agent_edit.md", "zh")


CREATION_CRUD_INSTRUCTIONS = template("agent_crud.md", "zh")


def render_creation_request(message: str, current_selection: dict | None = None) -> str:
    """Keep the user instruction isolated; current facts are read once through the tool."""
    payload = {"user_request": message}
    if current_selection is not None:
        payload["current_selection"] = current_selection
    return json.dumps(payload, ensure_ascii=False)


def render_turn_limit_instruction(language: str = "zh") -> str:
    return template("agent_turn_limit.md", language)


CREATION_SUMMARY_INSTRUCTIONS = template("agent_summary.md", "zh")


def render_creation_summary(previous: str, messages: list[dict]) -> str:
    return json.dumps(
        {"previous_summary": previous, "conversation_records": messages},
        ensure_ascii=False,
    )


def render_working_checkpoint(evidence: dict, language: str = "zh") -> str:
    """Historical evidence stays user/tool data, never new system authority."""
    return json.dumps(
        {"working_checkpoint": evidence, "notice": text("checkpoint_notice", language)},
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


def render_creation_instructions(
    *, language: str, crud: bool = False, turn_limited: bool = False
) -> str:
    instructions = template("agent_crud.md" if crud else "agent_edit.md", language)
    if turn_limited:
        instructions += "\n" + render_turn_limit_instruction(language)
    return instructions


def render_summary_instructions(language: str) -> str:
    return template("agent_summary.md", language)
