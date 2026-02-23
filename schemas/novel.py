from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from schemas._base import BaseResponse


# --- 核心业务属性 (Internal Mixins) ---

class NovelProperties(BaseModel):
    """
    最基础的属性集合，不含大字段。
    用于列表(List)、关联查询(Relation)等轻量场景。
    """
    name: Optional[str] = Field(None, description="小说名称", max_length=255)
    author: Optional[str] = Field(None, description="作者", max_length=255)
    description: Optional[str] = Field(None, description="描述")
    cover: Optional[str] = Field(None, description="封面图URL")
    total_chapters: Optional[int] = Field(None, description="总章节数")

class NovelFullProperties(NovelProperties):
    """
    完整的业务属性，包含 content 等大字段。
    用于创建、更新、详情。
    """
    content: Optional[str] = Field(None, description="正文内容")


# --- 输入 Schema (In-bound) ---

class NovelCreate(NovelFullProperties):
    """创建请求：name 必填"""
    name: str = Field(..., description="小说名称", max_length=255)


class NovelUpdate(NovelCreate):
    """全量更新：逻辑同创建"""
    pass


class NovelPatch(NovelFullProperties):
    """局部更新：全字段可选"""
    pass


# --- 输出 Schema (Out-bound) ---

class NovelBriefOut(NovelProperties, BaseResponse):
    """
    列表输出：仅返回简要信息，提升加载速度。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="小说/剧本ID")


class NovelOut(NovelFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="小说/剧本ID")
