"""Optional snapshot-owned speech budgets; no audio or persisted text is modified."""

import json
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prompts.skill_pack import SkillSnapshot
from prompts.storyboard import split_storyboard_voice_track
from schemas.scene import SoraScenePromptConfig
from utils.messages import localized_message


class SpeechTimingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    characters_per_second: tuple[float, float]
    words_per_second: tuple[float, float]
    pause_seconds: float = Field(ge=0)
    slack_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def ordered_rates(self):
        for minimum, maximum in (self.characters_per_second, self.words_per_second):
            if not 0 < minimum <= maximum:
                raise ValueError("Speech rates must be positive and ordered")
        return self

    def duration_range(self, text: str) -> tuple[float, float]:
        # shortcut: text budgets approximate pronunciation; use measured audio if dubbing is introduced.
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*", text)
        remainder = re.sub(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*", "", text)
        characters = sum(character.isalnum() for character in remainder)
        pauses = len(re.findall(r"[，,。.!！?？;；:：、…]+", text)) * self.pause_seconds
        fastest = characters / self.characters_per_second[1] + len(words) / self.words_per_second[1] + pauses
        slowest = characters / self.characters_per_second[0] + len(words) / self.words_per_second[0] + pauses
        return fastest, slowest + self.slack_seconds


class StoryboardSpeechValidator:
    """One instance per model run retains speech across timing repair attempts."""

    def __init__(self, snapshot: SkillSnapshot):
        contract = json.loads(snapshot.contents.get("storyboard_contract", "{}"))
        raw = contract.get("speech_timing")
        self.policy = SpeechTimingPolicy.model_validate(raw) if raw is not None else None
        self.original_speech: dict[tuple[str, str], str] | None = None

    def validate_shot(self, shot: SoraScenePromptConfig) -> None:
        if self.policy is None:
            return
        from services.storyboard.validation import TIMELINE

        for field in ("narration", "dialogue"):
            for index, line in enumerate(getattr(shot, field), 1):
                match = TIMELINE.match(line)
                _, text = split_storyboard_voice_track(line)
                if not match or not any(character.isalnum() for character in text):
                    raise ValueError(localized_message("人声条目必须包含时间轴、说话者和完整台词正文"))
                minimum, maximum = self.policy.duration_range(text)
                seconds = float(match[2]) - float(match[1])
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

    def validate(self, shots: Sequence[SoraScenePromptConfig]) -> None:
        if self.policy is None:
            return
        from services.storyboard.validation import TIMELINE

        speech: dict[tuple[str, str], str] = {}
        for shot in shots:
            for field in ("narration", "dialogue"):
                # Preserve chronology even if the model returns voice entries out of order.
                for line in sorted(getattr(shot, field), key=lambda value: float(match[1]) if (match := TIMELINE.match(value)) else 0):
                    prefix, text = split_storyboard_voice_track(line)
                    if not TIMELINE.match(line) or not any(character.isalnum() for character in text):
                        raise ValueError(localized_message("人声条目必须包含时间轴、说话者和完整台词正文"))
                    speaker = re.split(r"[（(]", TIMELINE.sub("", prefix), maxsplit=1)[0].rstrip(":： ")
                    speaker = speaker.removeprefix("@{").removesuffix("}")
                    key = (field, speaker)
                    speech[key] = speech.get(key, "") + re.sub(r'[\s「」『』“”"]', "", text)
        if self.original_speech is None:
            self.original_speech = speech
        elif speech != self.original_speech:
            raise ValueError(localized_message("时长修正必须完整保留首次候选的全部旁白、对白、说话者及各自台词顺序；只调整时间或拆镜，不得删减、改写、增加台词或更换说话者。"))
        for shot in shots:
            self.validate_shot(shot)
