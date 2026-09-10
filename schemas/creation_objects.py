"""Typed object discovery and change sets; no arbitrary database fields."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.creation_agent import AgentTarget, StoryboardVisualChanges
from schemas.scene import SoraScenePromptConfig


class CreationObjectQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["all", "asset", "variant", "scene", "chapter"] = "all"
    scope: Literal["chapter", "project"] = "chapter"
    chapter_id: int | None = Field(None, gt=0)
    asset_type: Literal[1, 2, 3] | None = None
    search: str = Field("", max_length=200)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=30)


ObjectRef = Annotated[int, Field(gt=0, strict=True)] | Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")]


class ChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateSetting(ChangeInput):
    operation: Literal['create_setting']
    client_ref: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=8000)
    prompt: str = Field(min_length=1, max_length=32000)
    chapter_ids: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, max_length=100)


class CreateAssetSetting(CreateSetting):
    """新增人物、场景或道具基础设定。"""
    kind: Literal['asset'] = 'asset'
    asset_type: Literal[1, 2, 3]
    aliases: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=30)
    is_global: bool = False


class CreateVariantSetting(CreateSetting):
    """已有角色的章内形态；父资产确定类型，没有 asset_type、aliases 或 is_global 参数。"""
    kind: Literal['variant']
    parent: ObjectRef


SettingCreation = Annotated[CreateAssetSetting | CreateVariantSetting, Field(discriminator='kind')]


class SettingFields(ChangeInput):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=8000)
    prompt: str | None = Field(None, min_length=1, max_length=32000)
    aliases: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(None, max_length=30)
    chapter_ids: list[Annotated[int, Field(gt=0, strict=True)]] | None = Field(None, max_length=100)
    is_global: bool | None = None

    @model_validator(mode='after')
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError('提供实际修改字段，未修改的字段省略，不传 null')
        return self


class UpdateSetting(ChangeInput):
    operation: Literal['update_setting']
    target: AgentTarget
    fields: SettingFields

    @model_validator(mode='after')
    def image_target(self):
        if self.target.kind == 'scene':
            raise ValueError('该工具只编辑设定和形态')
        if self.target.kind == 'variant' and (self.fields.aliases is not None or self.fields.is_global is not None):
            raise ValueError('形态的别名由父资产决定')
        return self


class CreateScene(ChangeInput):
    operation: Literal['create_scene']
    client_ref: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,39}$")
    chapter_id: int | None = Field(None, gt=0)
    # None appends; zero inserts at the beginning; a ref inserts after that scene.
    after: ObjectRef | Literal[0] | None = None
    description: str = Field(min_length=1, max_length=8000)
    duration: float = Field(ge=1, le=30, allow_inf_nan=False)
    assets: list[ObjectRef] = Field(default_factory=list, max_length=30)
    variant_refs: list[ObjectRef] = Field(default_factory=list, max_length=30)
    prompt: str | None = Field(None, min_length=1, max_length=32000)
    structure: SoraScenePromptConfig | None = None

    @model_validator(mode='after')
    def one_prompt(self):
        if (self.prompt is None) == (self.structure is None):
            raise ValueError('新增分镜必须提供完整文本或完整结构，二选一')
        return self


class SceneContentChanges(StoryboardVisualChanges):
    dialogue: list[str] | None = None
    narration: list[str] | None = None
    sound_design: str | None = Field(None, min_length=1)


class SceneFields(ChangeInput):
    description: str | None = Field(None, min_length=1, max_length=8000)
    duration: float | None = Field(None, ge=1, le=30, allow_inf_nan=False)
    assets: list[ObjectRef] | None = Field(None, max_length=30)
    variant_refs: list[ObjectRef] | None = Field(None, max_length=30)
    after: ObjectRef | Literal[0] | None = None
    prompt: str | None = Field(None, min_length=1, max_length=32000)
    visual: SceneContentChanges | None = None

    @model_validator(mode='after')
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError('至少提供一个修改字段')
        if self.prompt is not None and self.visual is not None:
            raise ValueError('纯文本和结构化 Prompt 修改二选一')
        if any(getattr(self, key) is None for key in self.model_fields_set - {'after'}):
            raise ValueError('未修改的字段省略，不传 null')
        return self


class UpdateScene(ChangeInput):
    operation: Literal['update_scene']
    scene_id: int = Field(gt=0)
    fields: SceneFields


class DeleteObject(ChangeInput):
    operation: Literal['delete']
    target: AgentTarget


CreationOperation = Annotated[SettingCreation | UpdateSetting | CreateScene | UpdateScene | DeleteObject, Field(discriminator='operation')]


class CreationChangeSet(ChangeInput):
    operations: list[CreationOperation] = Field(min_length=1, max_length=100)

    @model_validator(mode='before')
    @classmethod
    def default_setting_kind(cls, value):
        # Preserve the existing asset shorthand while exposing separate schemas
        # for new base settings and variants to the model.
        if isinstance(value, dict) and isinstance(value.get('operations'), list):
            value = {**value, 'operations': [
                {**item, 'kind': 'asset'} if isinstance(item, dict) and item.get('operation') == 'create_setting' and 'kind' not in item else item
                for item in value['operations']
            ]}
        return value

    @model_validator(mode='after')
    def unique_references(self):
        refs = [item.client_ref for item in self.operations if isinstance(item, (CreateSetting, CreateScene))]
        if len(set(refs)) != len(refs):
            raise ValueError('同一批新增对象的 client_ref 不能重复')
        return self
