"""One Chinese skill pack; pure rendering from an immutable run snapshot."""

from pathlib import Path
import hashlib
import json
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).with_name("skills")
FILES = {
    "base": "SKILL.md",
    **{
        name: name + ".md"
        for name in (
            "story",
            "assets",
            "image",
            "storyboard",
            "remake",
            "video",
            "editing",
            "authorization",
            "summary",
        )
    },
    "styles": "styles.json",
    "strategies": "strategies.json",
}


class SkillSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    contents: dict[str, str]

    def read(self, name: str) -> str:
        if name not in FILES or name not in self.contents:
            raise ValueError("Unknown skill")
        return self.contents[name]


def read_skill(name: str) -> str:
    return (ROOT / FILES[name]).read_text(encoding="utf-8")


def snapshot_skills() -> dict:
    contents = {name: read_skill(name) for name in FILES}
    revision = hashlib.sha256(
        json.dumps(contents, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return SkillSnapshot(revision=revision, contents=contents).model_dump()


def instructions(snapshot: SkillSnapshot, language: str, skill: str) -> str:
    return (
        snapshot.read("base")
        + "\n任务语言 language="
        + language
        + "\n"
        + snapshot.read(skill)
    )


def task_facts(value: object) -> str:
    return json.dumps({"untrusted_task_facts": value}, ensure_ascii=False, default=str)


def render_voice_bindings(bindings: list[dict]) -> str:
    """Protocol mapping only; prose and creative voice rules live in skills."""
    if not bindings:
        return ""
    return json.dumps(
        {
            "voice_bindings": [
                {
                    "subjects": item["subjects"],
                    "role": item["kind"],
                    "reference": f"[音频{item['index']}]",
                }
                for item in bindings
            ]
        },
        ensure_ascii=False,
    )
