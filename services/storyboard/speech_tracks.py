"""Preserve speakers and the words they say across storyboard repairs."""

import re
from collections.abc import Sequence

from prompts.storyboard import TIMELINE, split_storyboard_voice_track
from schemas.scene import SoraScenePromptConfig
from utils.messages import localized_message


def spoken_parts(line: str) -> tuple[float, str, str]:
    match = TIMELINE.match(line)
    prefix, text = split_storyboard_voice_track(line)
    label = prefix[match.end():-1].strip() if match else ''
    speaker = re.split(r"[（(]", label, maxsplit=1)[0].strip().removeprefix("@{").removesuffix("}")
    if not match or not speaker or not any(c.isalnum() for c in text):
        raise ValueError(localized_message("人声条目必须写成 0s-2s: 说话者（语气）：完整台词正文；时间后和说话者后都需要冒号"))
    return float(match[1]), speaker, text


class SpeechContent:
    def __init__(self):
        self.original_speech: dict[tuple[str, str], str] | None = None

    def validate(self, shots: Sequence[SoraScenePromptConfig]) -> None:
        speech: dict[tuple[str, str], str] = {}
        for shot in shots:
            for field in ("narration", "dialogue"):
                lines = sorted(map(spoken_parts, getattr(shot, field)), key=lambda part: part[0])
                for _, speaker, text in lines:
                    key = (field, speaker)
                    speech[key] = speech.get(key, "") + re.sub(r'[\s「」『』“”"]', "", text)
        if self.original_speech is None:
            self.original_speech = speech
        elif speech != self.original_speech:
            raise ValueError(localized_message("时长修正必须完整保留首次候选的全部旁白、对白、说话者及各自台词顺序；只调整时间或拆镜，不得删减、改写、增加台词或更换说话者。"))
