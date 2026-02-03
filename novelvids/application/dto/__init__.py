"""Data Transfer Objects for API layer."""

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

T = TypeVar("T")

from pydantic import BaseModel, EmailStr, Field


class BaseDTO(BaseModel):
    """Base DTO with common configuration."""

    class Config:
        from_attributes = True


# User DTOs
class UserCreateDTO(BaseModel):
    """DTO for creating a user."""

    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8)


class UserUpdateDTO(BaseModel):
    """DTO for updating a user."""

    username: str | None = None
    email: EmailStr | None = None


class LoginDTO(BaseModel):
    """DTO for user login."""

    username: str
    password: str


class UserResponseDTO(BaseDTO):
    """DTO for user response."""

    id: UUID
    username: str
    email: str
    is_active: bool
    balance: float
    created_at: datetime


class TokenDTO(BaseModel):
    """DTO for authentication token."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenDTO(BaseModel):
    """DTO for refresh token request."""

    refresh_token: str


# Novel DTOs
class NovelCreateDTO(BaseModel):
    """DTO for creating a novel."""

    title: str = Field(min_length=1, max_length=255)
    content: str | None = None
    author: str | None = None


class NovelUpdateDTO(BaseModel):
    """DTO for updating a novel."""

    title: str | None = None
    content: str | None = None
    author: str | None = None


class NovelResponseDTO(BaseDTO):
    """DTO for novel response."""

    id: UUID
    title: str
    author: str | None
    status: str
    workflow_status: str = "draft"
    total_chapters: int
    processed_chapters: int
    created_at: datetime
    updated_at: datetime


class NovelDetailDTO(NovelResponseDTO):
    """DTO for detailed novel response."""

    content: str | None = None
    metadata: dict[str, Any]

    # 工作流状态检查
    can_extract_chapters: bool = False
    can_extract_characters: bool = False
    can_create_storyboard: bool = False
    can_generate_video: bool = False


# Chapter DTOs
class ChapterCreateDTO(BaseModel):
    """DTO for creating a chapter manually."""

    title: str = Field(min_length=1, max_length=255)
    content: str | None = None
    number: int | None = None  # Auto-assign if not provided


class ChapterResponseDTO(BaseDTO):
    """DTO for chapter response."""

    id: UUID
    novel_id: UUID
    number: int
    title: str
    status: str
    workflow_status: str
    scene_count: int
    created_at: datetime


class ChapterDetailDTO(ChapterResponseDTO):
    """DTO for detailed chapter response."""

    content: str
    metadata: dict[str, Any]


# Scene DTOs
class SceneResponseDTO(BaseDTO):
    """DTO for scene response."""

    id: UUID
    chapter_id: UUID
    sequence: int
    description: str
    dialogue: str | None
    speaker_id: UUID | None
    image_url: str | None
    audio_url: str | None
    duration: float
    status: str


# Video DTOs
class VideoResponseDTO(BaseDTO):
    """DTO for video response."""

    id: UUID
    novel_id: UUID
    chapter_id: UUID | None
    title: str
    url: str | None
    duration: float
    resolution: str
    fps: int
    status: str
    created_at: datetime


# Workflow DTOs
class WorkflowCreateDTO(BaseModel):
    """DTO for creating a workflow."""

    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    workflow_json: dict[str, Any]
    category: str = "general"
    is_default: bool = False


class WorkflowResponseDTO(BaseDTO):
    """DTO for workflow response."""

    id: UUID
    name: str
    description: str | None
    category: str
    is_default: bool
    created_at: datetime


# Usage DTOs
class UsageRecordResponseDTO(BaseDTO):
    """DTO for usage record response."""

    id: UUID
    resource_type: str
    quantity: float
    unit_cost: float
    total_cost: float
    description: str | None
    created_at: datetime


class UsageSummaryDTO(BaseModel):
    """DTO for usage summary."""

    total_cost: float
    total_images: int
    total_audio_seconds: float
    total_video_seconds: float
    records: list[UsageRecordResponseDTO]


class ProcessNovelDTO(BaseModel):
    """DTO for novel processing request."""

    novel_id: UUID
    start_chapter: int = 1
    end_chapter: int | None = None
    generate_images: bool = True
    generate_audio: bool = True
    generate_video: bool = True


# Video Generation DTOs
class GenerateVideoDTO(BaseModel):
    """DTO for video generation request."""

    chapter_id: UUID
    shot_sequence: int
    platform: str = Field(default="vidu", description="Video platform: vidu or doubao")
    duration: float = Field(default=6.0, ge=1.0, le=10.0)
    aspect_ratio: str = Field(default="16:9")


class VideoTaskResponseDTO(BaseModel):
    """DTO for video generation task response."""

    task_id: str
    platform: str
    status: str
    progress: float = 0
    video_url: str | None = None
    error: str | None = None
    shot_sequence: int | None = None


# Chapter Processing DTOs
class ProcessChapterDTO(BaseModel):
    """DTO for chapter processing request."""

    chapter_id: UUID


class ProcessChaptersBatchDTO(BaseModel):
    """DTO for batch chapter processing request."""

    novel_id: UUID
    start_chapter: int = Field(default=1, ge=1)
    end_chapter: int | None = None


class VisualStateDTO(BaseDTO):
    """DTO for character visual state."""

    chapter_number: int
    alias_used: str
    current_state: str


class CharacterAssetDTO(BaseDTO):
    """DTO for character asset."""

    canonical_name: str
    character_type: str
    base_traits: str
    aliases: list[str]
    visual_states: list[VisualStateDTO]
    last_updated_chapter: int


class AssetCreateDTO(BaseModel):
    """DTO for creating an asset."""

    asset_type: str = Field(description="Asset type: person, scene, or item")
    canonical_name: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    base_traits: str | None = None
    is_global: bool = True
    source_chapters: list[int] = Field(default_factory=list)


class AssetUpdateDTO(BaseModel):
    """DTO for updating an asset."""

    canonical_name: str | None = None
    aliases: list[str] | None = None
    description: str | None = None
    base_traits: str | None = None
    main_image: str | None = None
    angle_image_1: str | None = None
    angle_image_2: str | None = None
    image_source: str | None = None
    is_global: bool | None = None
    source_chapters: list[int] | None = None


class AssetResponseDTO(BaseDTO):
    """DTO for asset response."""

    id: UUID
    novel_id: UUID
    asset_type: str
    canonical_name: str
    aliases: list[str]
    description: str | None
    base_traits: str | None
    main_image: str | None
    angle_image_1: str | None
    angle_image_2: str | None
    image_source: str
    is_global: bool
    source_chapters: list[int]
    last_updated_chapter: int
    created_at: datetime
    updated_at: datetime


class ChapterAssetCreateDTO(BaseModel):
    """DTO for creating a chapter-asset relationship."""

    asset_id: UUID
    state_description: str | None = None
    state_traits: str | None = None
    appearances: list[dict] = Field(default_factory=list)


class ChapterAssetResponseDTO(BaseDTO):
    """DTO for chapter-asset relationship response."""

    id: UUID
    chapter_id: UUID
    asset_id: UUID
    state_description: str | None
    state_traits: str | None
    appearances: list[dict]
    asset: AssetResponseDTO | None = None


class ExtractionRequestDTO(BaseModel):
    """DTO for extraction request."""

    types: list[str] = Field(
        default=["person", "scene", "item"],
        description="Types to extract: person, scene, item",
    )


class ExtractionResponseDTO(BaseDTO):
    """DTO for extraction response."""

    chapter_id: UUID
    chapter_number: int
    persons: list[dict]
    scenes: list[dict]
    items: list[dict]
    merged_count: int = 0


class ExtractedEntityDTO(BaseDTO):
    """DTO for extracted entity."""

    name: str
    entity_type: str
    visual_desc: str
    action_context: str


class AliasRelationDTO(BaseDTO):
    """DTO for alias relation."""

    alias: str
    canonical_name: str
    reason: str
    chapter_discovered: int


class ChapterExtractionResultDTO(BaseDTO):
    """DTO for chapter extraction result."""

    chapter_number: int
    entities: list[ExtractedEntityDTO]
    alias_relations: list[AliasRelationDTO]
    character_prompts: dict[str, str]


class CharacterPromptsDTO(BaseModel):
    """DTO for character prompts response."""

    novel_id: UUID
    chapter_number: int | None
    prompts: dict[str, str]


# Pagination
class PaginationDTO(BaseModel):
    """DTO for pagination parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponseDTO(BaseModel, Generic[T]):
    """DTO for paginated response."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
