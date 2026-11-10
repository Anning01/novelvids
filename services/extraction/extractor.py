"""Schema-validated model gateway for prepared asset extraction messages."""

import asyncio
import json
import re
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from services.llm.json_output import create_json_completion, completion_usage
from prompts.skill_pack import SkillSnapshot


ASSET_EXTRACTION_GATEWAY_ERROR_CODE = "asset_extraction_gateway_error"
ASSET_EXTRACTION_GATEWAY_ERROR_MESSAGE = (
    "资产提取模型调用失败"
    f"（错误代码：{ASSET_EXTRACTION_GATEWAY_ERROR_CODE}）"
)


class AssetExtractionGatewayError(RuntimeError):
    """Stable, content-free extraction boundary failure."""

    error_code = ASSET_EXTRACTION_GATEWAY_ERROR_CODE

    def __init__(self, usage: dict | None = None) -> None:
        super().__init__(ASSET_EXTRACTION_GATEWAY_ERROR_MESSAGE)
        self.usage = usage or {}


class ExtractedVariant(BaseModel):
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


def validate_asset_prompt_contract(result: AssetExtractionResult, snapshot: SkillSnapshot, language: str, aspect_ratio: str) -> None:
    """Validate new extraction output without rewriting saved or historical prompts."""
    assets = [(person, "group" if person.label == "群像" else "person") for person in result.persons]
    assets += [(scene, "scene") for scene in result.scenes]
    assets += [(item, "item") for item in result.items]
    for asset, kind in assets:
        validate_asset_design(asset.base_traits, kind, snapshot, language, aspect_ratio)
        if asset.variant:
            validate_asset_design(asset.variant.base_traits, kind, snapshot, language, aspect_ratio)


def validate_asset_design(text: str, kind: str, snapshot: SkillSnapshot, language: str, aspect_ratio: str) -> None:
    """Validate one asset or variant against the same immutable extraction contract."""
    if "asset_contract" not in snapshot.contents:
        return
    contracts = json.loads(snapshot.read("asset_contract")).get(language)
    if not contracts:
        return
    contract = contracts[kind]
    text = text.strip()
    task = contract["task"].format(aspect_ratio=aspect_ratio)
    if not text.startswith(task or contract["heading"]):
        raise ValueError(f"{kind}: use the complete task template verbatim at the start, with aspect_ratio={aspect_ratio}")
    heading = text.find(contract["heading"], len(task))
    if heading < 0:
        raise ValueError(f"{kind}: missing description heading {contract['heading']}")
    details = text[heading + len(contract["heading"]):].strip()
    suffix = contract.get("suffix", "")
    if suffix:
        if not details.endswith(suffix):
            raise ValueError(f"{kind}: preserve the complete template suffix: {suffix}")
        details = details[:-len(suffix)].strip()
    if not details:
        raise ValueError(f"{kind}: visual description must not be empty")
    fields = contract["fields"]
    if fields:
        lines = [line.strip() for line in details.splitlines() if line.strip()]
        matches = [re.fullmatch(r"\*\*(.+?)\*\*\s*[:：]\s*(.+)", line) for line in lines]
        if len(matches) != len(fields) or any(match is None or match[1] != field for match, field in zip(matches, fields)):
            raise ValueError(f"{kind}: description must contain exactly these ordered fields: {', '.join(fields)}")
        if any(match[2].strip().casefold() in {"", "无", "none", "未知", "unknown", "未提及", "not mentioned", "无法确认"} for match in matches):
            raise ValueError(f"{kind}: replace placeholders with concrete visual design")


# 保留结果容器，兼容已有内部调用和历史测试数据构造。
class PersonList(BaseModel):
    persons: list[Person] = Field(default_factory=list)


class SceneList(BaseModel):
    scenes: list[Scene] = Field(default_factory=list)


class ItemList(BaseModel):
    items: list[Item] = Field(default_factory=list)


class AssetExtractor:
    """Send prepared extraction messages through the shared Schema boundary."""

    response_model = AssetExtractionResult

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        supports_json_output: bool = False,
        prompt_language: str = "zh",
        required_assets: tuple[tuple[int, str], ...] = (),
        initial_assets: AssetExtractionResult | None = None,
        required_variants: tuple[tuple[int, str, str], ...] = (),
    ) -> None:
        self.client = client
        self.model = model
        self.supports_json_output = supports_json_output
        self.last_usage: dict = {}
        self.prompt_language = prompt_language
        self.required_assets = required_assets
        self.initial_assets = initial_assets
        self.required_variants = required_variants
        self.targeted_assets = None
        self.targeted = False
        self.not_applied_reason = None

    async def _validate_coverage(self, result: AssetExtractionResult) -> None:
        validate_required_design_assets(result, self.required_assets)
        if self.targeted:
            returned = {(kind, item.name) for field, kind in [('persons', 1), ('scenes', 2), ('items', 3)] for item in getattr(result, field)}
            if returned - set(self.required_assets) or any(item.variant for field in ('persons', 'scenes', 'items') for item in getattr(result, field)):
                from utils.messages import localized_message
                raise ValueError(localized_message('定点补漏只允许返回已核对的指定资产，不增加其他对象或衍生形态'))
        returned = {(kind, item.name, item.variant.name) for kind, items in
                    ((1, result.persons), (2, result.scenes), (3, result.items)) for item in items if item.variant}
        missing = [f'{name}/{variant}' for kind, name, variant in self.required_variants if (kind, name, variant) not in returned]
        if missing:
            from utils.messages import localized_message
            raise ValueError(localized_message('需要补全资产形态：{p0}', p0='、'.join(missing)))

    async def extract(
        self,
        messages: list[dict[str, str]],
    ) -> AssetExtractionResult:
        from services.creation_agent.skill_execution import current_execution
        execution = current_execution.get()
        if execution:
            from services.extraction.cast import read_chapter_cast
            from prompts.extraction import render_cast_scope
            from services.creation_agent.step_context import step_context
            context = await step_context(execution.params)
            self.targeted = bool(context and context.step.asset_scope == 'targeted')
            targets = None
            if self.targeted:
                targets = {'instructions': context.step.instructions,
                    'requirements': [item.model_dump(mode='json') for item in context.requirements]}
            cast = await read_chapter_cast(execution, messages, **({'target_requirements': targets} if targets is not None else {}))
            if self.targeted:
                from services.extraction.reuse import extraction_reuse
                self.targeted_assets = await extraction_reuse.targeted(execution, cast)
                self.required_assets = self.targeted_assets.required_assets
                if not self.required_assets:
                    from utils.messages import localized_message
                    self.not_applied_reason = localized_message('本章原文未找到指定资产的依据，请提供对应段落；已有设定已保留，未生成新资产')
                    return AssetExtractionResult(persons=[], scenes=[], items=[])
                if context.step.mode == 'fill_missing':
                    self.initial_assets = self.targeted_assets.accepted
                    if self.targeted_assets.complete:
                        return self.initial_assets
            else:
                self.required_assets = tuple(dict.fromkeys((*self.required_assets, *cast.required_assets())))
            messages = [*messages, {'role': 'user', 'content': render_cast_scope(self.prompt_language, cast.model_dump(mode='json'), self.required_assets)}]
            options = {'output_validator': self._validate_coverage} if self.required_assets else {}
            options['asset_scope'] = self.required_assets
            if self.initial_assets is not None:
                from prompts.extraction import render_asset_repair
                options['initial_assets'] = self.initial_assets
                issues = []
                try:
                    await self._validate_coverage(self.initial_assets)
                except ValueError as error:
                    issues.append(str(error))
                options['additional_instructions'] = render_asset_repair(self.prompt_language,
                    {field: [item.name for item in getattr(self.initial_assets, field)] for field in ('persons', 'scenes', 'items')}, issues)
            if self.targeted:
                from prompts.extraction import targeted_design_instructions
                options['additional_instructions'] = options.get('additional_instructions', '') + '\n' + targeted_design_instructions(self.prompt_language)
            return await execution.generate('assets', messages, self.response_model, **options)
        try:
            parsed, completion = await create_json_completion(
                self.client,
                model=self.model,
                messages=messages,
                response_model=self.response_model,
                supports_json_output=self.supports_json_output,
                prompt_language=self.prompt_language,
            )
            self.last_usage = completion_usage(completion)
            result = AssetExtractionResult.model_validate(parsed)
            await self._validate_coverage(result)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise AssetExtractionGatewayError(
                usage=getattr(error, "usage", None) or {}
            ) from None
