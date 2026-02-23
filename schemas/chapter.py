from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from schemas._base import BaseResponse
from utils.enums import TaskStatusEnum, WorkflowStatus


# --- 核心业务属性 (Internal Mixins) ---

class ChapterProperties(BaseModel):
    """
    最基础的属性集合，不含大字段。
    用于列表(List)、关联查询(Relation)等轻量场景。
    """
    number: Optional[int] = Field(None, description="章节序号")
    name: Optional[str] = Field(None, description="章节名称", max_length=255)
    status: Optional[int] = Field(None, description=TaskStatusEnum.__doc__)
    workflow_status: Optional[int] = Field(None, description=WorkflowStatus.__doc__)


class ChapterFullProperties(ChapterProperties):
    """
    完整的业务属性，包含 content 等大字段。
    用于创建、更新、详情。
    """
    content: Optional[str] = Field(None, description="正文内容")


# --- 输入 Schema (In-bound) ---

class ChapterCreate(ChapterFullProperties):
    """创建请求：name 必填"""
    number: int = Field(..., description="章节序号")
    name: str = Field(..., description="章节名称", max_length=255)
    content: str = Field(..., description="章节内容")
    novel_id: int = Field(..., description="所属小说/剧本")

class ChapterUpdate(ChapterCreate):
    """全量更新：逻辑同创建"""
    pass


class ChapterPatch(ChapterFullProperties):
    """局部更新：全字段可选"""
    pass


# --- 输出 Schema (Out-bound) ---

class ChapterBriefOut(ChapterProperties, BaseResponse):
    """
    列表输出：仅返回简要信息，提升加载速度。
    """

    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")
    id: int = Field(..., description="章节ID")


class ChapterOut(ChapterFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """

    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")
    id: int = Field(..., description="章节ID")
