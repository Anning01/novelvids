from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict

from schemas._base import BaseResponse
from utils.enums import AiTaskTypeEnum
from utils.image_protocol import ImageApiProtocol


# --- 核心业务属性 ---

class AiModelConfigProperties(BaseModel):
    """AI 模型配置属性。"""

    task_type: Optional[int] = Field(None, description=AiTaskTypeEnum.__doc__)
    task_types: Optional[list[int]] = Field(None, description="模型支持的任务类型列表")
    name: Optional[str] = Field(None, description="配置名称", max_length=100)
    base_url: Optional[str] = Field(None, description="API 地址", max_length=500)
    api_key: Optional[str] = Field(None, description="API Key", max_length=500)
    model: Optional[str] = Field(None, description="模型名称", max_length=200)
    api_protocol: ImageApiProtocol = Field(
        ImageApiProtocol.openai_compatible,
        description="接口协议；生图任务可选择 OpenAI、OpenRouter 兼容或火山方舟",
    )
    is_active: Optional[bool] = Field(None, description="是否启用")
    concurrency: Optional[int] = Field(None, description="并发数", ge=1)
    supports_json_output: Optional[bool] = Field(
        False,
        description="是否支持 response_format=json_object",
    )
    max_context_characters: Optional[int] = Field(
        None,
        description="四层业务消息允许的最大总字符数",
        ge=1,
    )


# --- 输入 Schema ---

class AiModelConfigCreate(AiModelConfigProperties):
    """创建请求：必填字段。"""

    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    task_types: list[int] = Field(default_factory=list, description="模型支持的任务类型列表")
    name: str = Field(..., description="配置名称", max_length=100)
    base_url: str = Field(..., description="API 地址", max_length=500)
    api_key: str = Field(..., description="API Key", max_length=500)
    model: str = Field(..., description="模型名称", max_length=200)


class AiModelConfigUpdate(AiModelConfigCreate):
    """全量更新：同创建。"""
    pass


class AiModelConfigPatch(AiModelConfigProperties):
    """局部更新：全字段可选。"""
    pass


# --- 输出 Schema ---

class AiModelConfigOut(AiModelConfigProperties, BaseResponse):
    """配置输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="配置ID")
    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    task_types: list[int] = Field(default_factory=list, description="模型支持的任务类型列表")
    name: str = Field(..., description="配置名称")
    is_active: bool = Field(..., description="是否启用")
    concurrency: int = Field(..., description="并发数")
    supports_json_output: bool = Field(False, description="是否支持结构化 JSON 输出")
    max_context_characters: Optional[int] = Field(
        None,
        description="四层业务消息允许的最大总字符数",
        ge=1,
    )
    api_protocol: ImageApiProtocol = Field(
        ImageApiProtocol.openai_compatible,
        description="模型接口协议",
    )


class GeneralConfigUpdate(BaseModel):
    """应用级通用配置更新请求。"""

    prompt_language: Literal["zh", "en"] = Field(
        ...,
        description="新生成的图片提示词与镜头提示词语言",
    )


class GeneralConfigOut(GeneralConfigUpdate, BaseResponse):
    """应用级通用配置输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="配置ID")
