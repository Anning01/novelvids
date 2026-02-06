from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Any
from schemas._base import BaseResponse
from utils.enums import AssetTypeEnum, ImageSourceEnum


# --- 核心业务属性 (Internal Mixins) ---

class AssetProperties(BaseModel):
    """
    最基础的属性集合，不含大字段。
    用于列表(List)、关联查询(Relation)等轻量场景。
    """
    asset_type: Optional[AssetTypeEnum] = Field(None, description=AssetTypeEnum.__doc__)
    canonical_name: Optional[str] = Field(None, description="资产名称")
    aliases: Optional[list[str]] = Field(None, description="别名列表", examples=["张三", "小张"])
    # 描述信息
    description: Optional[str] = Field(None, description="详细描述")
    base_traits: Optional[str] = Field(None, description="固有特征 (英文, 用于 prompt)")
    # 图片资产
    main_image: Optional[str] = Field(None, description="三视主图")
    angle_image_1: Optional[str] = Field(None, description="可选参考图1")
    angle_image_2: Optional[str] = Field(None, description="可选参考图2")
    image_source: Optional[ImageSourceEnum] = Field(None, description=ImageSourceEnum.__doc__)
    # 状态追踪
    is_global: Optional[bool] = Field(None, description="是否全局资产")
    source_chapters: Optional[list[int]] = Field(None, description="出现的章节列表")
    last_updated_chapter: Optional[int] = Field(None, description="出现最新章节")



class AssetFullProperties(AssetProperties):
    """
    完整的业务属性，包含 content 等大字段。
    用于创建、更新、详情。
    """
    # 元数据
    metadata: Optional[Any] = Field(None, description="元数据")


# --- 输入 Schema (In-bound) ---

class AssetCreate(AssetFullProperties):
    """创建请求：name 必填"""
    asset_type: AssetTypeEnum = Field(..., description=AssetTypeEnum.__doc__)
    novel_id: int = Field(..., description="所属小说/剧本")
    canonical_name: str = Field(max_length=100, description="资产名称")

    # 关键点：允许传入 chapter_id 来建立初始关联
    chapter_id: Optional[int] = Field(None, description="关联的特定章节ID（可选）")

class AssetUpdate(AssetCreate):
    """全量更新：逻辑同创建"""
    pass


class AssetPatch(AssetFullProperties):
    """局部更新：全字段可选"""
    pass


# --- 输出 Schema (Out-bound) ---

class AssetBriefOut(AssetProperties, BaseResponse):
    """
    列表输出：仅返回简要信息，提升加载速度。
    """
    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")

    id: int = Field(..., description="小说/剧本ID")


class AssetOut(AssetFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """
    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")

    id: int = Field(..., description="小说/剧本ID")
