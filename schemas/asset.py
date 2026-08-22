from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from schemas._base import BaseResponse
from schemas.asset_variant import AssetVariantOut
from utils.enums import AssetTypeEnum, ImageSourceEnum
from services.oss import resolve_media_url


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
    base_traits: Optional[str] = Field(
        None,
        description="用户可编辑并最终发送的完整生图提示词",
    )
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


class AssetReferencePromptPreview(BaseModel):
    """Build the exact prompt that will be sent to the reference-image model."""

    asset_type: AssetTypeEnum
    canonical_name: str = ""
    base_traits: str = ""
    description: str = ""
    metadata: Optional[Any] = None
    aspect_ratio: str = "16:9"


class AssetReferencePromptOut(BaseModel):
    prompt: str
    prompt_language: str


class AssetReferenceCreate(BaseModel):
    """Submit an asset image-generation run with optional image references."""

    variant_id: Optional[int] = Field(default=None, ge=1)
    reference_images: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("reference_images")
    @classmethod
    def validate_reference_images(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            value = raw.strip()
            if not value or len(value) > 8192:
                raise ValueError("参考图片地址不能为空且长度需在 8192 字符以内")
            if not value.startswith(("/media/", "uploads/", "http://", "https://")):
                raise ValueError("参考图片必须是已上传图片或完整 URL")
            if value not in normalized:
                normalized.append(value)
        return normalized


class AssetGenerationRecordOut(BaseModel):
    """Safe, presentation-ready summary of one asset image-generation run."""

    id: UUID
    status:  int
    images: list[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    model: Optional[str] = None
    clarity: Optional[str] = None
    aspect_ratio: Optional[str] = None
    output_format: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _resolve_media(self):
        self.images = [resolve_media_url(u) for u in self.images or []]
        return self


class AssetImageEditCreate(BaseModel):
    """Persist an annotation result as a new image history entry.

    ``image_url`` 支持三种来源：本地媒体路径（``/media/...``）、OSS 直传对象 key
    （``uploads/...``，落库时经内网校验存在性）、完整 URL（兼容历史数据）。
    """

    image_url: str
    source_image_url: Optional[str] = None
    output_format: str = "png"

    @field_validator("image_url")
    @classmethod
    def validate_media_url(cls, value: str) -> str:
        if not value or len(value) > 2000:
            raise ValueError("标注图地址不能为空且长度需在 2000 字符以内")
        if value.startswith(("/media/", "uploads/", "http://", "https://", "data:")):
            return value
        raise ValueError("标注图地址必须是本地媒体路径、OSS 对象 key 或完整 URL")


# --- 输出 Schema (Out-bound) ---

class AssetBriefOut(AssetProperties, BaseResponse):
    """
    列表输出：仅返回简要信息，提升加载速度。
    """
    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")

    id: int = Field(..., description="小说/剧本ID")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.main_image = resolve_media_url(self.main_image)
        self.angle_image_1 = resolve_media_url(self.angle_image_1)
        self.angle_image_2 = resolve_media_url(self.angle_image_2)
        meta = getattr(self, "metadata", None)
        if isinstance(meta, dict) and isinstance(meta.get("image_gallery"), list):
            self.metadata = {
                **meta,
                "image_gallery": [
                    resolve_media_url(u) for u in meta["image_gallery"]
                ],
            }
        if isinstance(meta, dict) and isinstance(meta.get("generation_reference_images"), list):
            self.metadata = {
                **meta,
                "generation_reference_images": [
                    resolve_media_url(u) for u in meta["generation_reference_images"]
                ],
            }
        return self


class AssetOut(AssetFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """
    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")

    id: int = Field(..., description="小说/剧本ID")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.main_image = resolve_media_url(self.main_image)
        self.angle_image_1 = resolve_media_url(self.angle_image_1)
        self.angle_image_2 = resolve_media_url(self.angle_image_2)
        meta = getattr(self, "metadata", None)
        if isinstance(meta, dict) and isinstance(meta.get("image_gallery"), list):
            self.metadata = {
                **meta,
                "image_gallery": [
                    resolve_media_url(u) for u in meta["image_gallery"]
                ],
            }
        if isinstance(meta, dict) and isinstance(meta.get("generation_reference_images"), list):
            self.metadata = {
                **meta,
                "generation_reference_images": [
                    resolve_media_url(u) for u in meta["generation_reference_images"]
                ],
            }
        return self


class AssetWithVariantsOut(AssetOut):
    variants: Optional[list[AssetVariantOut]] = Field(None, description="人物变装、场景升级或道具形态")


class AssetMergeRequest(BaseModel):
    """Merge source into target while keeping the target asset identity."""

    source_asset_id: int
    target_asset_id: int


class AssetMergeOut(BaseModel):
    asset: AssetWithVariantsOut
    removed_asset_id: int
    data_source_asset_id: int
    image_source_asset_id: Optional[int] = None
    summary: list[str] = Field(default_factory=list)
