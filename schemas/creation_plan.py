"""Versioned, server-owned creative plans; references never grant authority."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanConfirmation(PlanModel):
    task_id: UUID
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class CreativeRequirement(PlanModel):
    id: str = Field(min_length=1, max_length=80)
    instruction: str = Field(min_length=1, max_length=2000)
    source_quote: str = Field(min_length=1, max_length=8000)
    chapter_ids: list[int] = Field(default_factory=list)
    acceptance: str = Field(min_length=1, max_length=2000)


class CreationBrief(PlanModel):
    operations: list[Literal['assets', 'storyboard', 'image', 'video']] = Field(default_factory=list)
    read_chapter_ids: list[int] = Field(default_factory=list)
    write_chapter_ids: list[int] = Field(default_factory=list)
    asset_chapter_ids: list[int] = Field(default_factory=list, description='仅提取文字资产的来源章；不授权修改正文或分镜')
    asset_mode: Literal['fill_missing', 'revise'] = Field('fill_missing',
        description='资产操作模式：已有成果不用重做用 fill_missing；明确重新提取或修改已有设定用 revise')
    asset_scope: Literal['chapter', 'targeted'] = Field('chapter',
        description='整章提取用 chapter；用户指出某个遗漏的角色、场景或道具，仅核对补全这些对象用 targeted')
    write_selection: Literal['current', 'chapters', 'project'] = 'current'
    read_chapter_numbers: list[int] = Field(default_factory=list)
    project_scope_quote: str | None = None
    requirements: list[CreativeRequirement] = Field(default_factory=list)
    missing_material: list[str] = Field(default_factory=list)


class SourceSelection(PlanModel):
    chapter_id: int = Field(gt=0)
    start: int = Field(0, ge=0, description='服务器填写的原文起点；选用段落或 reference_id 时无需计算')
    end: int = Field(1, gt=0, description='服务器填写的原文终点；选用段落或 reference_id 时无需计算')
    first_paragraph: int | None = Field(None, ge=1)
    last_paragraph: int | None = Field(None, ge=1)
    reference_id: str | None = Field(None, max_length=160)
    quote: str | None = Field(None, max_length=8000, description='逐字复制的原文片段；服务器据此定位，不依赖模型计算字符位置')


class SourceExcerpt(SourceSelection):
    text: str


class SourceReading(PlanModel):
    summary: str = Field(min_length=1, max_length=4000)
    candidates: list[SourceSelection] = Field(default_factory=list, max_length=10)


class ChapterEvidence(PlanModel):
    chapter_id: int
    number: int
    name: str
    version: str
    characters: int
    pages: list[SourceReading]
    coverage: list[tuple[int, int]] = Field(default_factory=list)


class CreationPlanStep(PlanModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,60}$')
    operation: Literal['assets', 'storyboard', 'image', 'video']
    target_id: int | None = Field(None, gt=0)
    variant_id: int | None = Field(None, gt=0)
    source_step: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    mode: Literal['fill_missing', 'regenerate', 'revise'] = 'fill_missing'
    asset_scope: Literal['chapter', 'targeted'] = 'chapter'
    requirement_ids: list[str] = Field(default_factory=list)
    sources: list[SourceSelection] = Field(default_factory=list)
    asset_ids: list[int] = Field(default_factory=list)
    variant_ids: list[int] = Field(default_factory=list)
    instructions: str = Field(min_length=1, max_length=8000)
    label: str = Field(min_length=1, max_length=255)

    @model_validator(mode='after')
    def one_target(self):
        if (self.target_id is None) == (self.source_step is None):
            raise ValueError('Use one concrete target or one earlier step output')
        if self.source_step and self.source_step not in self.depends_on:
            raise ValueError('Output target must be an explicit dependency')
        if self.source_step and self.operation not in {'image', 'video'}:
            raise ValueError('Only media steps can consume produced object collections')
        if self.variant_id and self.operation != 'image':
            raise ValueError('Variant targets require image generation')
        return self


class CreationPlanDraft(PlanModel):
    summary: str = Field(min_length=1, max_length=4000)
    steps: list[CreationPlanStep] = Field(min_length=1)

    @model_validator(mode='after')
    def ordered_dependencies(self):
        seen = set()
        for step in self.steps:
            if step.id in seen or not set(step.depends_on) <= seen:
                raise ValueError('Steps must have unique IDs and earlier dependencies')
            seen.add(step.id)
        return self


class CreationPlan(CreationPlanDraft):
    version: Literal[1] = 1
    novel_id: int
    source_message_id: int
    original_request: dict
    brief: CreationBrief
    chapters: list[ChapterEvidence] = Field(default_factory=list)
    excerpts: list[SourceExcerpt] = Field(default_factory=list)
    object_versions: dict[str, str] = Field(default_factory=dict)
    object_scopes: dict[str, list[str]] = Field(default_factory=dict)
    chapter_scenes: dict[str, dict[str, str]] = Field(default_factory=dict)


class CreationStepContext(PlanModel):
    version: Literal[1] = 1
    step: CreationPlanStep
    original_message: str
    requirements: list[CreativeRequirement]
    sources: list[SourceExcerpt]
    assets: list[dict] = Field(default_factory=list)
    constraints: list[dict] = Field(default_factory=list)
    upstream_results: dict[str, dict] = Field(default_factory=dict)
    coalesced_step_ids: list[str] = Field(default_factory=list)


class RequirementFinding(PlanModel):
    requirement_id: str
    passed: bool
    location: str
    detail: str
    shot_sequences: list[int] = Field(default_factory=list, description='Existing storyboard shot numbers that require editing; [] when not localizable')


class CreativeCheck(PlanModel):
    findings: list[RequirementFinding]
    plan_followed: bool
    issues: list[str] = Field(default_factory=list)

    @property
    def passed(self):
        return self.plan_followed and not self.issues and all(item.passed for item in self.findings)
