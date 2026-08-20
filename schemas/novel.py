from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Optional
from schemas._base import BaseResponse
from services.oss import resolve_media_url


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
    tags: Optional[list[str]] = Field(None, description="项目标签", max_length=30)
    story_outline: Optional[str] = Field(None, description="故事大纲")
    project_type: Optional[str] = Field(
        None,
        description="项目设定类型",
        max_length=120,
    )
    project_setting: Optional[str] = Field(None, description="项目设定说明")
    storyboard_strategy: Optional[str] = Field(
        None,
        description="分镜策略名称",
        max_length=120,
    )
    style_key: Optional[str] = Field(
        None,
        description="视觉风格 key",
        max_length=64,
    )
    storyboard_setting: Optional[str] = Field(None, description="分镜策略说明")


# --- 输入 Schema (In-bound) ---

class NovelCreate(NovelFullProperties):
    """创建请求：name 必填"""
    name: str = Field(..., description="小说名称", max_length=255)
    # OSS 直传后由服务端经内网读取并解析正文，避免书稿正文经浏览器中转。
    # 提供 source_key 时无需再传 content（服务端解析后覆盖）。
    source_key: Optional[str] = Field(None, description="OSS 对象 key", max_length=500)
    source_filename: Optional[str] = Field(None, description="源文件名", max_length=255)


class NovelUpdate(NovelCreate):
    """全量更新：逻辑同创建"""
    pass


class NovelPatch(NovelFullProperties):
    """局部更新：全字段可选"""
    pass


# --- 输出 Schema (Out-bound) ---

class NovelMetaOut(NovelProperties, BaseResponse):
    """轻量元信息：不含书稿正文，供剧本/分镜页面入口使用。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tags: Optional[list[str]] = Field(None, description="项目标签")
    style_key: Optional[str] = Field(None, description="视觉风格 key", max_length=64)
    content_length: int = Field(0, description="书稿正文字符数（校验拆分质量用）")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.cover = resolve_media_url(self.cover)
        return self


class NovelBriefOut(NovelProperties, BaseResponse):
    """
    列表输出：仅返回简要信息，提升加载速度。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="小说/剧本ID")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.cover = resolve_media_url(self.cover)
        return self


class NovelOut(NovelFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="小说/剧本ID")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.cover = resolve_media_url(self.cover)
        return self
