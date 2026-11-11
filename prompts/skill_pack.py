"""Shared creative rules and immutable run snapshots."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import hashlib
import json
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).with_name("skills")
FILES = {
    "asset_contract": "novelvids-assets/references/asset_contract.json",
    "asset_lifecycle": "novelvids-assets/references/asset_lifecycle.md",
    "asset_templates": "novelvids-assets/references/asset_templates.json",
    "assets": "novelvids-assets/references/assets.md",
    "authorization": "runtime/authorization.md",
    "base": "runtime/base.md",
    "clip_templates": "novelvids-video/references/clip_templates.json",
    "creation_planning": "novelvids-planning/references/creation_planning.md",
    "creative_check": "novelvids-planning/references/creative_check.md",
    "editing": "novelvids-editing/references/editing.md",
    "editing_templates": "novelvids-editing/references/editing_templates.json",
    "image": "novelvids-image/references/image.md",
    "image_templates": "novelvids-image/references/image_templates.json",
    "plan_templates": "novelvids-planning/references/plan_templates.json",
    "planning_request": "novelvids-planning/references/planning_request.md",
    "remake": "novelvids-remake/references/remake.md",
    "remake_templates": "novelvids-remake/references/remake_templates.json",
    "screenplay": "novelvids-screenplay/references/screenplay.md",
    "source_reading": "novelvids-story/references/source_reading.md",
    "story": "novelvids-story/references/story.md",
    "storyboard": "novelvids-storyboard/references/storyboard.md",
    "storyboard_contract": "novelvids-storyboard/references/storyboard_contract.json",
    "storyboard_templates": "novelvids-storyboard/references/storyboard_templates.json",
    "strategies": "novelvids-storyboard/references/strategies.json",
    "structured": "runtime/structured.md",
    "styles": "novelvids-image/references/styles.json",
    "summary": "runtime/summary.md",
    "turn_limited": "runtime/turn_limited.md",
    "video": "novelvids-video/references/video.md",
}


class SkillSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    contents: dict[str, str]

    def read(self, name: str) -> str:
        if name not in FILES or name not in self.contents:
            raise ValueError("Unknown skill")
        return self.contents[name]

    def template(self, resource: str, key: str) -> str:
        # Historical snapshots predate externalization of these fixed renderer texts.
        content = self.read(resource) if resource in self.contents else read_skill(resource)
        return json.loads(content)[key]


_active_snapshot: ContextVar[SkillSnapshot | None] = ContextVar("active_skill_snapshot", default=None)


@contextmanager
def use_skill_snapshot(raw: dict | None):
    snapshot = SkillSnapshot.model_validate(raw) if raw else None
    token = _active_snapshot.set(snapshot)
    try:
        yield
    finally:
        _active_snapshot.reset(token)


def template_text(resource: str, key: str, language: str) -> str:
    return json.loads(read_skill(resource))[key]["en" if language == "en" else "zh"]


def read_skill(name: str) -> str:
    snapshot = _active_snapshot.get()
    if snapshot is not None and name in snapshot.contents:
        return snapshot.read(name)
    path = ROOT / FILES[name]
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        if not content.strip():
            raise ValueError(f"Invalid {name}: instructions must not be empty")
    else:
        try:
            resource = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid {name}: expected a JSON object") from None
        if not isinstance(resource, dict):
            raise ValueError(f"Invalid {name}: expected a JSON object")
        if name == "styles" and any(
            not isinstance(style, dict)
            or any(not isinstance(style.get(field), str) or not style[field].strip()
                   for field in ("label", "image", "video"))
            for style in resource.values()
        ):
            raise ValueError("Invalid styles: expected label, image and video strings")
    return content


def snapshot_skills() -> dict:
    active = _active_snapshot.get()
    if active is not None:
        return active.model_dump()
    contents = {name: read_skill(name) for name in FILES}
    revision = hashlib.sha256(
        json.dumps(contents, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return SkillSnapshot(revision=revision, contents=contents).model_dump()


def instructions(snapshot: SkillSnapshot, language: str, skill: str, *, output_kind: str | None = None) -> str:
    remake_shots = skill == 'remake' and output_kind == 'professional_video_prompt_material'
    remake_assets = skill == 'remake' and not remake_shots
    contract = ""
    if skill == "assets" or remake_assets:
        # Extraction writes final image prompts, so layout rules cannot be optional tool reads.
        contract = "\n" + snapshot.read("image")
    if remake_assets:
        contract += "\n" + snapshot.read("assets")
        contract += snapshot.template("remake_templates", "extract")
    if remake_shots:
        contract += '\n' + snapshot.read('storyboard')
        contract += snapshot.template("remake_templates", "shots")
    if skill in {"assets", "editing", "image"} or remake_assets:
        if "asset_contract" in snapshot.contents:
            specification = json.loads(snapshot.read("asset_contract")).get(language)
            if specification:
                contract += (
                    snapshot.template("asset_templates", "contract") + json.dumps(specification, ensure_ascii=False)
                )
    if (skill == "storyboard" or remake_shots) and "storyboard_contract" in snapshot.contents:
        from prompts.labels import prompt_label
        specification = json.loads(snapshot.read("storyboard_contract"))
        specification["sections"] = [prompt_label(section, language) for section in specification["sections"]]
        contract += snapshot.template("storyboard_templates", "contract") + json.dumps(specification, ensure_ascii=False)
    if skill in {"assets", "storyboard"} and "asset_lifecycle" in snapshot.contents:
        contract += "\n" + snapshot.read("asset_lifecycle")
    return (
        snapshot.read("base")
        + "\n任务语言 language="
        + language
        + "\n"
        + snapshot.read(skill)
        + contract
    )


def render_skill(skill: str, language: str, *, output_kind: str | None = None) -> str:
    return instructions(SkillSnapshot.model_validate(snapshot_skills()), language, skill, output_kind=output_kind)


def task_facts(value: object) -> str:
    return json.dumps({"untrusted_task_facts": value}, ensure_ascii=False, default=str)


def creative_requirements(text: str, language: str) -> str:
    header = template_text("editing_templates", "requirements", language)
    return header + text


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
