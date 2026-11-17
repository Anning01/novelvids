"""Asset result data types shared by generation, persistence and editing."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator





class ExtractedVariant(BaseModel):
    existing_variant_id: int | None = Field(default=None, gt=0, description="复用时填写同一基础资产下的目录形态 ID；新形态留空")
    name: str = Field(min_length=1, max_length=100, description="衍生形态名；与目录中相同形态必须使用相同名称")
    description: str = Field(default="", description="形态的剧情阶段与适用情境")
    base_traits: str = Field(min_length=1, description="遵循当前资产输出协议的完整形态生图提示词")
    change_reason: str = Field(min_length=1, description="原文中支持重大外形变化的具体依据；复用时说明与已有形态相同")

    @field_validator("name", "base_traits", "change_reason")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Visual variant fields must not be blank")
        return value.strip()


class ExtractedAppearance(BaseModel):
    variant: ExtractedVariant | None = Field(default=None,
        description="本章有重大外形变化或沿用已有衍生时填写；普通措辞差异、动作表情、光线变化为 null，沿用基础形象")


class Person(ExtractedAppearance):
    name: str = Field(description="标准名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    label: Literal["人物", "动物", "群像"] = Field(
        default="人物",
        description="资产形态",
    )
    description: str = Field(default="", description="任务指定语言的剧情语义说明")
    base_traits: str = Field(description="任务语言的完整生图提示词：具体稳定体貌、五官发型、服饰材质配色、群像个体差异（如适用）、项目风格与参考图版式；不能只给身份概述")

    @field_validator("label", mode="before")
    @classmethod
    def normalize_label(cls, value):
        return {"person": "人物", "animal": "动物", "group": "群像"}.get(value, value) if isinstance(value, str) else value

    @field_validator("base_traits")
    @classmethod
    def validate_visual_prompt(cls, value: str) -> str:
        from utils.prompt_language import skill_workflow
        if skill_workflow.get() and not value.strip():
            raise ValueError("Visual prompt must not be empty")
        return value

    @property
    def reference_layout(self) -> Literal["character_turnaround", "group_portrait"]:
        return "group_portrait" if self.label == "群像" else "character_turnaround"


class Scene(ExtractedAppearance):
    name: str = Field(description="场景名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(default="", description="任务指定语言的剧情语义说明")
    base_traits: str = Field(description="任务语言的完整场景生图提示词：空间规模拓扑、分层位置关系、固定陈设、材质光照、项目风格与四格透视版式")


class Item(ExtractedAppearance):
    name: str = Field(description="道具名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(default="", description="任务指定语言的剧情语义说明")
    base_traits: str = Field(description="任务语言的完整道具生图提示词：轮廓比例、材质配色、部件结构、纹样磨损、识别特征、项目风格与参考图背景")


class AssetExtractionResult(BaseModel):
    """一次模型响应同时返回全部资产类型。"""

    persons: list[Person] = Field(description="人物资产列表")
    scenes: list[Scene] = Field(description="场景资产列表")
    items: list[Item] = Field(description="道具资产列表")


def validate_required_design_assets(result: AssetExtractionResult, required_assets: tuple[tuple[int, str], ...]) -> None:
    from utils.enums import AssetTypeEnum
    from utils.messages import localized_message

    returned = {(kind.value, item.name.strip())
        for kind, items in ((AssetTypeEnum.person, result.persons),
                            (AssetTypeEnum.scene, result.scenes), (AssetTypeEnum.item, result.items))
        for item in items if item.base_traits.strip()}
    missing = [f'{AssetTypeEnum(kind).nickname}/{name}' for kind, name in required_assets if (kind, name.strip()) not in returned]
    if missing:
        raise ValueError(localized_message('本章应提取的资产尚未补全正式设定，请按原标准名返回完整提示词：{p0}', p0='、'.join(missing)))


def validate_asset_design(text: str) -> None:
    from utils.messages import localized_message

    if not text.strip():
        raise ValueError(localized_message('提示词不能为空'))
