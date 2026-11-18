"""The public VoiceDesign request uses the WAV subset of Chat Completions."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


VoiceText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class VoiceMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: VoiceText


class VoiceAudioOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["wav"] = "wav"
    optimize_text_preview: bool = False


class VoiceDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=200)
    messages: list[VoiceMessage] = Field(min_length=1, max_length=2)
    audio: VoiceAudioOptions
    stream: Literal[False] = False

    @model_validator(mode="after")
    def validate_messages(self):
        roles = [message.role for message in self.messages]
        if roles != ["user", "assistant"] and not (roles == ["user"] and self.audio.optimize_text_preview):
            raise ValueError("Voice design requires a user description followed by an assistant line to read")
        return self
