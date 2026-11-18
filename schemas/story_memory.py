"""Host-owned contracts for evidence, review and explicit story decisions."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoryModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class StoryEvidence(StoryModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    source: Literal['project.setting', 'project.outline', 'project.description', 'chapter.text', 'opening_chapter.text']
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('证据区间必须非空')
        return self


class StorySubjectProposal(StoryModel):
    ref: str = Field(min_length=1, max_length=100)
    existing_id: int | None = Field(default=None, gt=0)
    kind: Literal['character', 'world', 'location', 'organization', 'item', 'storyline']
    name: str = Field(min_length=1, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=30)


class StoryScope(StoryModel):
    world_ref: str | None = None
    scene: str | None = None
    from_chapter: int | None = Field(default=None, ge=1)
    until_chapter: int | None = Field(default=None, ge=1)
    story_time: str | None = None

    @model_validator(mode='after')
    def ordered(self):
        if self.from_chapter and self.until_chapter and self.until_chapter < self.from_chapter:
            raise ValueError('事实适用的章节区间无效')
        return self


class StoryFactProposal(StoryModel):
    subject_ref: str = Field(min_length=1, max_length=100)
    category: Literal['world', 'rule', 'identity', 'relation', 'event', 'state', 'outline', 'decision']
    nature: Literal['fact', 'testimony', 'inference', 'plan', 'creative_decision']
    content: str = Field(min_length=1, max_length=8000)
    scope: StoryScope
    evidence: list[StoryEvidence] = Field(min_length=1, max_length=20)
    operation: Literal['add', 'replace', 'retract']
    replaces_id: int | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def replacement(self):
        if (self.operation == 'add') != (self.replaces_id is None):
            raise ValueError('替代或撤回必须明确指定旧事实；新增不能指定旧事实')
        return self


class StoryCandidate(StoryModel):
    subjects: list[StorySubjectProposal] = Field(max_length=300)
    facts: list[StoryFactProposal] = Field(max_length=500)
    summary: str = Field(min_length=1, max_length=8000)
    ending_state: str = Field(max_length=8000)
    unresolved: list[str] = Field(max_length=100)

    @model_validator(mode='after')
    def references(self):
        refs = {subject.ref: subject for subject in self.subjects}
        if len(refs) != len(self.subjects):
            raise ValueError('候选对象引用不能重复')
        identities = {(s.kind, s.name) for s in self.subjects}
        existing = [s.existing_id for s in self.subjects if s.existing_id]
        if len(identities) != len(self.subjects) or len(existing) != len(set(existing)):
            raise ValueError('同一个故事对象只能声明一次')
        replaced = [f.replaces_id for f in self.facts if f.replaces_id]
        if len(replaced) != len(set(replaced)):
            raise ValueError('同一旧事实不能在一个提交中多次替代')
        for fact in self.facts:
            if fact.subject_ref not in refs:
                raise ValueError('事实引用了未声明的对象')
            if fact.scope.world_ref and (fact.scope.world_ref not in refs or refs[fact.scope.world_ref].kind != 'world'):
                raise ValueError('世界引用必须指向本候选中声明的世界')
        used = {fact.subject_ref for fact in self.facts} | {fact.scope.world_ref for fact in self.facts}
        if set(refs) - used:
            raise ValueError('故事对象必须由候选事实或世界范围提供依据')
        return self


class StoryReviewIssue(StoryModel):
    severity: Literal['blocking', 'warning']
    fact_index: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=4000)


class StoryReview(StoryModel):
    issues: list[StoryReviewIssue] = Field(max_length=500)
    summary: str = Field(min_length=1, max_length=8000)


class StoryAnalysisRequest(StoryModel):
    request_id: UUID
    chapter_id: int | None = Field(default=None, gt=0)
    assistant_model_config_id: int | None = Field(default=None, gt=0)
    skill_id: int | None = Field(default=None, ge=0)


class StoryCandidateUpdate(StoryModel):
    expected_revision: int = Field(ge=1)
    candidate: StoryCandidate


class StoryReviewRequest(StoryModel):
    expected_revision: int = Field(ge=1)
    assistant_model_config_id: int | None = Field(default=None, gt=0)


class StoryRepairRequest(StoryReviewRequest):
    expected_package_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class StoryDecision(StoryModel):
    expected_package_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: Literal['accept', 'reject']
    note: str = Field(default='', max_length=4000)


class StoryRecheckRequest(StoryModel):
    request_id: UUID
    from_chapter_id: int | None = Field(default=None, gt=0)
    assistant_model_config_id: int | None = Field(default=None, gt=0)
    skill_id: int | None = Field(default=None, ge=0)
