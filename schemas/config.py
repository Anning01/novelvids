from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from schemas._base import BaseResponse
from utils.enums import AiTaskTypeEnum


# --- 核心业务属性 ---

class AiModelConfigProperties(BaseModel):
    """AI 模型配置属性。"""

    task_type: Optional[int] = Field(None, description=AiTaskTypeEnum.__doc__)
    name: Optional[str] = Field(None, description="配置名称", max_length=100)
    base_url: Optional[str] = Field(None, description="API 地址", max_length=500)
    api_key: Optional[str] = Field(None, description="API Key", max_length=500)
    model: Optional[str] = Field(None, description="模型名称", max_length=200)
    is_active: Optional[bool] = Field(None, description="是否启用")
    concurrency: Optional[int] = Field(None, description="并发数", ge=1)


# --- 输入 Schema ---

class AiModelConfigCreate(AiModelConfigProperties):
    """创建请求：必填字段。"""

    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
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
    name: str = Field(..., description="配置名称")
    is_active: bool = Field(..., description="是否启用")
    concurrency: int = Field(..., description="并发数")
