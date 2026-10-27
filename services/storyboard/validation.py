"""Validate the saved prompt against structured output before any chapter writes."""

import json
import re

from collections.abc import Sequence
from prompts.labels import prompt_label
from prompts.skill_pack import SkillSnapshot
from prompts.storyboard import normalized_storyboard_reference_fields, split_storyboard_voice_track, format_storyboard_prompt
from schemas.scene import SoraScenePromptConfig, SceneEntity
from utils.messages import localized_message

TIMELINE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*[-–—~]\s*(\d+(?:\.\d+)?)\s*s?\s*[:：]")
CONTENT_FIELDS = (
    "visual_style", "format_and_look", "lenses_and_filtration", "lighting_and_atmosphere",
    "grade_and_palette", "camera_movement", "time_setting", "environment", "spatial_relationships",
    "visual_prose", "actions", "narration", "dialogue", "sound_design", "transition",
    "effect_restrictions", "allowed_effects",
)


def validate_skill_storyboard_timing(shot: SoraScenePromptConfig) -> None:
    for name in CONTENT_FIELDS:
        value = getattr(shot, name)
        if isinstance(value, str) and not value.strip() or name == "actions" and not value:
            raise ValueError(localized_message("分镜结构化内容不能为空：{p0}", p0=name))
    duration = float(shot.duration.removesuffix("s"))
    voices = []
    for name in ("actions", "narration", "dialogue"):
        for line in getattr(shot, name):
            match = TIMELINE.match(line)
            if not match or not 0 <= float(match[1]) < float(match[2]) <= duration + .001:
                raise ValueError(localized_message("分镜时间轴缺失或超出镜头时长：{p0}", p0=name))
            if name != "actions":
                if "@{" in split_storyboard_voice_track(line)[1]:
                    raise ValueError(localized_message("台词或旁白正文不能包含素材引用，请保留原文内容"))
                voices.append((float(match[1]), float(match[2])))
    voices.sort()
    if any(current[0] < previous[1] - .001 for previous, current in zip(voices, voices[1:])):
        raise ValueError(localized_message("分镜中的对白、旁白或内心独白时间重叠"))


def prepare_skill_storyboard(storyboard, snapshot: SkillSnapshot, language: str,
                             entities: Sequence[SceneEntity], strategy_key: str):
    from schemas.agent_workflow import SkillStoryboard, SkillShot
    from prompts.storyboard_strategies import StoryboardStrategyPrompt

    resource = json.loads(snapshot.read("strategies"))[strategy_key]
    strategy = StoryboardStrategyPrompt(key=strategy_key, name=strategy_key, description="",
                                      prohibitions=resource["restrictions"], generation_rules=resource["rules"])
    shots = []
    for shot in storyboard.shots:
        validate_skill_storyboard_timing(shot)
        normalized = shot.model_copy(update=normalized_storyboard_reference_fields(shot, entities))
        prompt = format_storyboard_prompt(normalized, language, entities=entities, strategy=strategy,
                                         localize_strategy=False)
        prepared = SkillShot.model_validate({**normalized.model_dump(), "prompt": prompt})
        validate_skill_storyboard_shot(prepared, snapshot, language, entities)
        shots.append(prepared)
    return SkillStoryboard(shots=shots)


def validate_skill_storyboard_shot(shot: SoraScenePromptConfig, snapshot: SkillSnapshot, language: str,
                                   entities: Sequence[SceneEntity] = ()) -> None:
    if "storyboard_contract" not in snapshot.contents:
        return
    contract = json.loads(snapshot.read("storyboard_contract"))
    shot = shot.model_copy(update=normalized_storyboard_reference_fields(shot, entities))
    prompt = shot.prompt or ""
    position = 0
    for section in contract["sections"]:
        label = prompt_label(section, language)
        index = prompt.find(label, position)
        if index < 0:
            raise ValueError(localized_message("分镜提示词缺少完整栏目：{p0}", p0=label))
        position = index + len(label)
    compact = lambda value: re.sub(r"\s+", "", value).casefold()
    text = compact(prompt)
    for name in CONTENT_FIELDS:
        values = getattr(shot, name)
        for value in values if isinstance(values, list) else [values]:
            if value.strip() and compact(value) not in text:
                raise ValueError(localized_message("分镜提示词遗漏结构化内容：{p0}", p0=name))
    duration = float(shot.duration.removesuffix("s"))
    if f"@{{镜头时长:{duration:g}s}}" not in prompt:
        raise ValueError(localized_message("分镜提示词缺少镜头时长标记"))
    validate_skill_storyboard_timing(shot)
