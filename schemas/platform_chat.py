from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class TextPart(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["text"]
    text: str


class ImageUrl(BaseModel):
    model_config = ConfigDict(extra="allow")
    url: HttpUrl
    detail: Literal["auto", "low", "high"] | None = None


class ImagePart(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["image_url"]
    image_url: ImageUrl


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system","developer","user","assistant","tool","function"]
    content: str | list[TextPart | ImagePart | dict] | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    reasoning_content: str | None = None
    function_call: dict | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    model: str = Field(min_length=1, max_length=200)
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    stream_options: dict[str, bool] | None = None
    max_tokens: int | None = Field(None, gt=0)
    max_completion_tokens: int | None = Field(None, gt=0)
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    seed: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    reasoning_effort: str | None = None
    thinking: dict | None = None
    tools: list[dict] | None = None
    tool_choice: str | dict | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict | None = None

    @model_validator(mode="after")
    def validate_options(self):
        if "audio" in ((self.model_extra or {}).get("modalities") or []):
            raise ValueError("Inline audio output is not supported; use media URLs")
        if self.stream_options is not None and not self.stream:
            raise ValueError("stream_options requires stream=true")
        if self.max_completion_tokens and self.max_tokens:
            raise ValueError("Choose one token limit")
        return self
