"""Structured production inputs; natural-language layout belongs to skills."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from schemas.scene import SoraScenePromptConfig
from schemas.video import VideoGenerationOptions
from schemas.video_export import ExportEnhanceIn


class CompletePrompt(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)


class SkillShot(SoraScenePromptConfig):
    prompt: str = Field(
        min_length=1, max_length=100_000, description="独立完整、实际发送的视频提示词"
    )


class SkillStoryboard(BaseModel):
    shots: list[SkillShot] = Field(min_length=1, max_length=200)


class StructuredSkillShot(SoraScenePromptConfig):
    prompt: None = None
    reference_only_types: list[Literal["人物", "场景", "物品"]] = Field(
        default_factory=lambda: ["人物", "场景", "物品"],
        max_length=3,
        description="参考图通过名称引用，不把生图版式写进视频内容",
    )


class StructuredSkillStoryboard(BaseModel):
    shots: list[StructuredSkillShot] = Field(min_length=1, max_length=200)


class ProductionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["story", "assets", "image", "storyboard", "remake", "video", "compose", "prepare_export", "enhance_export"]
    target_id: int = Field(gt=0)
    media_model_config_id: int | None = Field(None, gt=0)
    request_id: UUID
    variant_id: int | None = Field(None, gt=0)
    video_options: VideoGenerationOptions | None = None
    replace_existing: bool = False
    enhancement: ExportEnhanceIn | None = None

    @model_validator(mode="after")
    def validate_options(self):
        if self.variant_id is not None and self.operation != "image":
            raise ValueError("variant_id requires image")
        if self.video_options is not None and self.operation != "video":
            raise ValueError("video_options requires video")
        if self.replace_existing and self.operation != "storyboard":
            raise ValueError("replace_existing requires storyboard")
        if self.enhancement is not None and self.operation != 'enhance_export':
            raise ValueError('enhancement requires enhance_export')
        return self


class RemakeAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=100_000)
    label: Literal["人物", "动物", "群像"] = "人物"


class RemakeAssets(BaseModel):
    characters: list[RemakeAsset] = Field(max_length=100)
    scenes: list[RemakeAsset] = Field(max_length=100)
    objects: list[RemakeAsset] = Field(max_length=100)


class RemakeReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1, max_length=100)
    asset_name: str = Field(min_length=1, max_length=255)
    asset_type: Literal["character", "scene", "object"]


class RemakeShot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=100_000)
    asset_refs: list[RemakeReference] = Field(max_length=30)
    confidence: float = Field(ge=0, le=1)


class RequestedProduction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["story", "assets", "image", "storyboard", "remake", "video", "compose", "prepare_export", "enhance_export"]
    target_id: int = Field(gt=0)
    source_quote: str = Field(min_length=1, max_length=8000)
    variant_id: int | None = Field(None, gt=0)


class ProductionAuthorization(BaseModel):
    intents: list[RequestedProduction] = Field(default_factory=list, max_length=100)
