"""Optional snapshot-owned speech budgets; no audio or persisted text is modified."""

import json
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prompts.skill_pack import SkillSnapshot
from prompts.skills.scripts.check_speech import (
    PACE_ERROR, delivery_factor, issue_values, measure, pace_issues, parse_line, speaker_aliases,
)
from schemas.scene import SoraScenePromptConfig
from utils.messages import localized_message


class SpeakerContinuity(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    max_rate_ratio: float = Field(gt=1)
    min_sample_seconds: float = Field(gt=0)
    slow_rate_factor: float = Field(gt=0, lt=1)
    slow_cues: list[str] = Field(min_length=1)


class SpeechTimingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    characters_per_second: tuple[float, float]
    words_per_second: tuple[float, float]
    pause_seconds: float = Field(ge=0)
    slack_seconds: float = Field(ge=0)
    continuity: SpeakerContinuity | None = None

    @model_validator(mode="after")
    def ordered_rates(self):
        for minimum, maximum in (self.characters_per_second, self.words_per_second):
            if not 0 < minimum <= maximum:
                raise ValueError("Speech rates must be positive and ordered")
        return self


class StoryboardSpeechValidator:
    """One instance per model run retains speech across timing repair attempts."""

    def __init__(self, snapshot: SkillSnapshot):
        contract = json.loads(snapshot.contents.get("storyboard_contract", "{}"))
        raw = contract.get("speech_timing")
        self.policy = SpeechTimingPolicy.model_validate(raw) if raw is not None else None
        self.settings = self.policy.model_dump() if self.policy else None
        self.original_speech: dict[tuple[str, str], str] | None = None

    def validate_shot(self, shot: SoraScenePromptConfig) -> None:
        if self.policy is None:
            return

        for field in ("narration", "dialogue"):
            for index, line in enumerate(getattr(shot, field), 1):
                try:
                    parsed = parse_line(line)
                except ValueError as error:
                    raise ValueError(localized_message(str(error))) from None
                factor = delivery_factor(parsed, self.settings["continuity"])
                minimum, maximum, _, _ = measure(parsed.text, self.settings, factor)
                seconds = parsed.end - parsed.start
                if seconds + .001 < minimum:
                    raise ValueError(localized_message(
                        "第 {p0} 镜 {p1} 第 {p2} 句时间不足：已分配 {p3} 秒，自然语速至少需 {p4} 秒。请保留全部台词及说话者，拆成连续独立镜头，各镜时间轴从零开始并遵守镜头时长范围；不得删词、改写或强行加速。",
                        p0=shot.sequence, p1=field, p2=index, p3=f"{seconds:g}", p4=f"{minimum:.2f}",
                    ))
                if seconds > maximum + .001:
                    raise ValueError(localized_message(
                        "第 {p0} 镜 {p1} 第 {p2} 句人声时段过长：自然语速预计不超过 {p3} 秒。请缩短人声时间窗，剩余时间留白给动作和环境声，不得拖长发音或增删台词。",
                        p0=shot.sequence, p1=field, p2=index, p3=f"{maximum:.2f}",
                    ))

    def continuity_issues(self, shots, entities=()):
        if not self.policy or not self.policy.continuity:
            return []
        tracks = [shot.model_dump(include={"sequence", "dialogue", "narration"}) for shot in shots]
        aliases = speaker_aliases([entity.model_dump() if isinstance(entity, BaseModel) else entity for entity in entities])
        return [(index, localized_message(PACE_ERROR, **issue_values(issue)))
                for index, issue in pace_issues(tracks, self.settings, aliases)]

    def validate(self, shots: Sequence[SoraScenePromptConfig], entities=()) -> None:
        if self.policy is None:
            return

        speech: dict[tuple[str, str], str] = {}
        for shot in shots:
            for field in ("narration", "dialogue"):
                # Preserve chronology even if the model returns voice entries out of order.
                try:
                    lines = sorted((parse_line(raw) for raw in getattr(shot, field)), key=lambda line: line.start)
                except ValueError as error:
                    raise ValueError(localized_message(str(error))) from None
                for line in lines:
                    key = (field, line.speaker)
                    speech[key] = speech.get(key, "") + re.sub(r'[\s「」『』“”"]', "", line.text)
        if self.original_speech is None:
            self.original_speech = speech
        elif speech != self.original_speech:
            raise ValueError(localized_message("时长修正必须完整保留首次候选的全部旁白、对白、说话者及各自台词顺序；只调整时间或拆镜，不得删减、改写、增加台词或更换说话者。"))
        for shot in shots:
            self.validate_shot(shot)
        issues = self.continuity_issues(shots, entities)
        if issues:
            raise ValueError(issues[0][1])
