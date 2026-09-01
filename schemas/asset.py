from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from schemas._base import BaseResponse
from schemas.asset_variant import AssetVariantOut
from services.cover_derivatives import image_derivative_reference
from utils.enums import AssetTypeEnum, ImageSourceEnum
from services.oss import normalize_media_url, resolve_media_url


def _image_urls(
    image: str | None,
) -> tuple[str | None, str | None, str | None]:
    """从持久化引用分别解析原图、缩略图和预览图地址。"""
    stored = normalize_media_url(image)
    return (
        resolve_media_url(stored),
        resolve_media_url(image_derivative_reference(stored, "thumbnail")),
        resolve_media_url(image_derivative_reference(stored, "preview")),
    )


def _resolve_asset_metadata(metadata: Any) -> Any:
    if not isinstance(metadata, dict):
        return metadata
    resolved = dict(metadata)
    for key in ("image_gallery", "generation_reference_images"):
        values = metadata.get(key)
        if not isinstance(values, list):
            continue
        images = [_image_urls(value) for value in values if isinstance(value, str)]
        resolved[key] = [original for original, _thumbnail, _preview in images if original]
        resolved[f"{key}_thumbnails"] = [
            thumbnail for _original, thumbnail, _preview in images
        ]
        resolved[f"{key}_previews"] = [
            preview for _original, _thumbnail, preview in images
        ]
    return resolved


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
    is_current: bool = False
    images: list[str] = Field(default_factory=list)
    image_thumbnails: list[str | None] = Field(default_factory=list)
    image_previews: list[str | None] = Field(default_factory=list)
    error_message: Optional[str] = None
    model: Optional[str] = None
    clarity: Optional[str] = None
    aspect_ratio: Optional[str] = None
    output_format: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _resolve_media(self):
        resolved = [_image_urls(image) for image in self.images or []]
        self.images = [original for original, _thumbnail, _preview in resolved if original]
        self.image_thumbnails = [thumbnail for _original, thumbnail, _preview in resolved]
        self.image_previews = [preview for _original, _thumbnail, preview in resolved]
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
    # 资产编辑器需要从列表响应恢复音色、形态与生成参数等持久化设置。
    metadata: Optional[Any] = Field(None, description="资产编辑元数据")

    id: int = Field(..., description="小说/剧本ID")
    main_image_thumbnail: Optional[str] = Field(None, description="三视主图缩略图")
    main_image_preview: Optional[str] = Field(None, description="三视主图预览图")
    angle_image_1_thumbnail: Optional[str] = Field(None, description="参考图1缩略图")
    angle_image_1_preview: Optional[str] = Field(None, description="参考图1预览图")
    angle_image_2_thumbnail: Optional[str] = Field(None, description="参考图2缩略图")
    angle_image_2_preview: Optional[str] = Field(None, description="参考图2预览图")

    @model_validator(mode="after")
    def _resolve_media(self):
        (
            self.main_image,
            self.main_image_thumbnail,
            self.main_image_preview,
        ) = _image_urls(self.main_image)
        (
            self.angle_image_1,
            self.angle_image_1_thumbnail,
            self.angle_image_1_preview,
        ) = _image_urls(self.angle_image_1)
        (
            self.angle_image_2,
            self.angle_image_2_thumbnail,
            self.angle_image_2_preview,
        ) = _image_urls(self.angle_image_2)
        self.metadata = _resolve_asset_metadata(getattr(self, "metadata", None))
        return self


class AssetOut(AssetFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """
    model_config = ConfigDict(from_attributes=True)
    novel_id: int = Field(..., description="所属小说/剧本")

    id: int = Field(..., description="小说/剧本ID")
    main_image_thumbnail: Optional[str] = Field(None, description="三视主图缩略图")
    main_image_preview: Optional[str] = Field(None, description="三视主图预览图")
    angle_image_1_thumbnail: Optional[str] = Field(None, description="参考图1缩略图")
    angle_image_1_preview: Optional[str] = Field(None, description="参考图1预览图")
    angle_image_2_thumbnail: Optional[str] = Field(None, description="参考图2缩略图")
    angle_image_2_preview: Optional[str] = Field(None, description="参考图2预览图")

    @model_validator(mode="after")
    def _resolve_media(self):
        (
            self.main_image,
            self.main_image_thumbnail,
            self.main_image_preview,
        ) = _image_urls(self.main_image)
        (
            self.angle_image_1,
            self.angle_image_1_thumbnail,
            self.angle_image_1_preview,
        ) = _image_urls(self.angle_image_1)
        (
            self.angle_image_2,
            self.angle_image_2_thumbnail,
            self.angle_image_2_preview,
        ) = _image_urls(self.angle_image_2)
        self.metadata = _resolve_asset_metadata(getattr(self, "metadata", None))
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
