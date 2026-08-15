"""Schema-validated model gateway for prepared asset extraction messages."""

import asyncio
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

from prompts.extraction import (
    GROUP_PORTRAIT_TRAIT_LABELS,
    SINGLE_CHARACTER_TRAIT_LABELS,
    ensure_ordered_trait_labels,
)
from services.llm.json_output import create_json_completion, completion_usage


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


class Person(BaseModel):
    name: str = Field(description="标准名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    label: Literal["人物", "动物", "群像"] = Field(
        default="人物",
        description="资产形态",
    )
    description: str = Field(default="", description="中文剧情语义说明")
    base_traits: str = Field(description="目标提示词语言的稳定视觉描述")

    @model_validator(mode="after")
    def validate_visual_contract(self) -> "Person":
        if self.label == "群像":
            ensure_ordered_trait_labels(
                self.base_traits,
                GROUP_PORTRAIT_TRAIT_LABELS,
                "群像视觉描述",
            )
        else:
            ensure_ordered_trait_labels(
                self.base_traits,
                SINGLE_CHARACTER_TRAIT_LABELS,
                "单人或动物视觉描述",
            )
        return self

    @property
    def reference_layout(self) -> Literal["character_turnaround", "group_portrait"]:
        return "group_portrait" if self.label == "群像" else "character_turnaround"


class Scene(BaseModel):
    name: str = Field(description="场景名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(default="", description="中文剧情语义说明")
    base_traits: str = Field(description="目标提示词语言的稳定场景视觉描述")


class Item(BaseModel):
    name: str = Field(description="道具名称")
    aliases: list[str] = Field(default_factory=list, description="别名列表")
    description: str = Field(default="", description="中文剧情语义说明")
    base_traits: str = Field(description="目标提示词语言的稳定道具视觉描述")


class AssetExtractionResult(BaseModel):
    """一次模型响应同时返回全部资产类型。"""

    persons: list[Person] = Field(description="人物资产列表")
    scenes: list[Scene] = Field(description="场景资产列表")
    items: list[Item] = Field(description="道具资产列表")


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
    ) -> None:
        self.client = client
        self.model = model
        self.supports_json_output = supports_json_output
        self.last_usage: dict = {}

    async def extract(
        self,
        messages: list[dict[str, str]],
    ) -> AssetExtractionResult:
        try:
            parsed, completion = await create_json_completion(
                self.client,
                model=self.model,
                messages=messages,
                response_model=self.response_model,
                supports_json_output=self.supports_json_output,
            )
            self.last_usage = completion_usage(completion)
            return AssetExtractionResult.model_validate(parsed)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise AssetExtractionGatewayError(
                usage=getattr(error, "usage", None) or {}
            ) from None
