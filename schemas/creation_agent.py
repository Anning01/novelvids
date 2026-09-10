"""Narrow contracts for creation-agent prompt edits."""

from typing import Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from schemas.scene import ScenePromptSegment


class AgentConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    request_limit: int = Field(6, ge=1, le=30)
    tool_calls_limit: int = Field(8, ge=1, le=100)
    max_targets: int = Field(8, ge=1, le=100)
    timeout_seconds: int = Field(180, ge=10, le=900)
    max_context_characters: int = Field(64000, ge=2000, le=200000)
    history_runs: int = Field(6, ge=1, le=30)
    max_output_tokens: int = Field(8000, ge=256, le=16000)
    total_tokens_limit: int = Field(100000, ge=1000, le=500000)


class AgentTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["asset", "variant", "scene"]
    id: int = Field(gt=0, strict=True)


class PromptStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_id: int | None = Field(None, gt=0)
    targets: list[AgentTarget] = Field(min_length=1, max_length=100)


class PendingConstraintOut(BaseModel):
    id: int
    content: str


class PromptTargetStatusOut(AgentTarget):
    pending_constraints: list[PendingConstraintOut] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: UUID
    message: str = Field(min_length=1, max_length=8000)
    chapter_id: int | None = Field(None, gt=0)
    model_config_id: int | None = Field(None, gt=0)
    targets: list[AgentTarget] = Field(default_factory=list, max_length=100)
    # Missing on historical requests means the original selected-only contract.
    write_scope: Literal['selected', 'chapter', 'project', 'read_only'] = 'selected'

    @model_validator(mode="after")
    def unique_targets(self):
        if len({(target.kind, target.id) for target in self.targets}) != len(self.targets):
            raise ValueError("不能重复选择同一目标")
        return self


class AgentConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    novel_id: int = Field(gt=0)


class AgentConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    novel_id: int
    active_task_id: UUID | None
    created_at: datetime
    updated_at: datetime
    title: str = "新会话"


class PromptChangeItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["asset", "variant", "scene"]
    operation: Literal['create', 'update', 'delete'] = 'update'
    target_id: int
    asset_id: int | None = None
    target_label: str | None = None
    chapter_id: int | None = None
    recovery: dict = Field(default_factory=dict)
    constraint_ids: list[int] = Field(default_factory=list)
    before: dict
    after: dict
    after_version: str


class PromptChangeOut(BaseModel):
    id: int
    task_id: UUID
    changes: list[PromptChangeItemOut]
    reverted_at: datetime | None
    created_at: datetime


class CreationQueryItemOut(BaseModel):
    kind: Literal['asset', 'variant', 'scene', 'chapter']
    id: int
    name: str
    asset_id: int | None = None
    chapter_id: int | None = None


class CreationQueryResultOut(BaseModel):
    items: list[CreationQueryItemOut]
    total: int
    has_more: bool


class AgentRunOut(BaseModel):
    task_id: UUID
    conversation_id: int
    status: int
    content: str
    error_message: str | None = None
    changes: list[PromptChangeOut] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    event_count: int = 0
    query_results: list[CreationQueryResultOut] = Field(default_factory=list)


class AgentMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    task_id: UUID
    status: int
    changes: list[PromptChangeOut] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    created_at: datetime
    query_results: list[CreationQueryResultOut] = Field(default_factory=list)


class AgentMessagePage(BaseModel):
    items: list[AgentMessageOut]
    next_before: int | None


class CreationConstraintScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["project", "chapter", "targets", "range"]
    chapter_id: int | None = Field(None, gt=0)
    start_chapter: int | None = Field(None, gt=0)
    end_chapter: int | None = Field(None, gt=0)
    asset_id: int | None = Field(None, gt=0)
    targets: list[AgentTarget] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def explicit_scope(self):
        if self.kind == "chapter" and self.chapter_id is None:
            raise ValueError("章节约束必须指定章节")
        if self.kind == "targets" and not self.targets:
            raise ValueError("局部约束必须指定已有目标集合")
        if self.kind == "range" and (self.start_chapter is None or self.end_chapter is None or self.end_chapter < self.start_chapter):
            raise ValueError("剧情区间必须具有明确起止章节，不能猜测终点")
        if self.kind != "chapter" and self.chapter_id is not None:
            raise ValueError("作用范围包含无关章节字段")
        if self.kind != "range" and (self.start_chapter is not None or self.end_chapter is not None):
            raise ValueError("作用范围包含无关区间字段")
        if self.kind != "targets" and self.targets:
            raise ValueError("作用范围包含无关目标集合")
        return self


class CreationConstraintProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=2000)
    source_quote: str = Field(min_length=2, max_length=2000)
    scope: CreationConstraintScope
    supersedes_id: int | None = Field(None, gt=0)


class CreationReply(BaseModel):
    """Final reply with optional user-sourced creative memory, never extra business tools."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=8000)
    constraints: list[CreationConstraintProposal] = Field(default_factory=list, max_length=12)


class PromptEditInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # Optimistic concurrency tokens are captured and injected by the server.
    # They are intentionally absent from the model-facing tool schema because
    # opaque hashes are easy for a model to copy incorrectly.
    expected_version: SkipJsonSchema[str | None] = None


class ImagePromptEdit(PromptEditInput):
    target_kind: Literal["asset", "variant"]
    target_id: int = Field(gt=0)
    prompt: str = Field(min_length=1)


def _omit_null_patch_defaults(schema: dict) -> None:
    for field in schema.get('properties', {}).values():
        if field.get('default') is None:
            field.pop('default', None)


class StoryboardVisualChanges(BaseModel):
    """Only visual prompt fields; tracks, duration and bindings remain read-only."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra=_omit_null_patch_defaults)

    shot_size_and_camera: str | SkipJsonSchema[None] = Field(None, min_length=1)
    visual_style: str | SkipJsonSchema[None] = Field(None, min_length=1)
    effect_restrictions: list[str] | SkipJsonSchema[None] = None
    time_setting: str | SkipJsonSchema[None] = Field(None, min_length=1)
    environment: str | SkipJsonSchema[None] = Field(None, min_length=1)
    spatial_relationships: str | SkipJsonSchema[None] = Field(None, min_length=1)
    visual_prose: str | SkipJsonSchema[None] = Field(None, min_length=1)
    actions: list[str] | SkipJsonSchema[None] = Field(None, min_length=1)
    format_and_look: str | SkipJsonSchema[None] = Field(None, min_length=1)
    lenses_and_filtration: str | SkipJsonSchema[None] = Field(None, min_length=1)
    lighting_and_atmosphere: str | SkipJsonSchema[None] = Field(None, min_length=1)
    grade_and_palette: str | SkipJsonSchema[None] = Field(None, min_length=1)
    camera_movement: str | SkipJsonSchema[None] = Field(None, min_length=1)
    transition: str | SkipJsonSchema[None] = Field(None, min_length=1)
    allowed_effects: list[str] | SkipJsonSchema[None] = None
    segments: list[ScenePromptSegment] | SkipJsonSchema[None] = None

    @model_validator(mode='before')
    @classmethod
    def reject_explicit_null(cls, values):
        if isinstance(values, dict) and any(value is None for value in values.values()):
            raise ValueError('未修改的字段请省略，不接受 null 字段')
        return values

    @model_validator(mode="after")
    def require_actual_changes(self):
        if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("至少提供一项非空的 Prompt 修改，不接受 null 字段")
        return self


class StoryboardPromptEdit(PromptEditInput):
    scene_id: int = Field(gt=0)
    changes: StoryboardVisualChanges | None = None
    legacy_prompt: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def select_one_mode(self):
        if (self.changes is None) == (self.legacy_prompt is None):
            raise ValueError("结构化修改和历史纯文本修改必须且只能选择一种")
        return self
