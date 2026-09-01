from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas._base import BaseResponse
from services.cover_derivatives import image_derivative_reference
from services.oss import normalize_media_url, resolve_media_url


class AssetVariantProperties(BaseModel):
    name: Optional[str] = Field(None, max_length=100, description="形态名称")
    description: Optional[str] = Field(None, description="该形态的中文描述")
    base_traits: Optional[str] = Field(
        None,
        description="该形态用户可编辑并最终发送的完整生图提示词",
    )
    chapter_numbers: Optional[list[int]] = Field(None, description="适用章节序号")
    images: Optional[list[str]] = Field(None, description="多张参考图")
    metadata: Optional[Any] = Field(None, description="扩展生成参数")


class AssetVariantCreate(AssetVariantProperties):
    name: str = Field(..., max_length=100, description="形态名称")


class AssetVariantPatch(AssetVariantProperties):
    pass


class AssetVariantChapterAssignment(BaseModel):
    chapter_number: int = Field(..., ge=1, description="设置为该集唯一使用的衍生形态")


class AssetVariantOut(AssetVariantProperties, BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    name: str
    chapter_numbers: list[int] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    image_thumbnails: list[str | None] = Field(default_factory=list)
    image_previews: list[str | None] = Field(default_factory=list)

    @model_validator(mode="after")
    def _resolve_media(self):
        stored = [normalize_media_url(image) for image in self.images or []]
        self.images = [resolved for image in stored if (resolved := resolve_media_url(image))]
        self.image_thumbnails = [
            resolve_media_url(image_derivative_reference(image, "thumbnail"))
            for image in stored
        ]
        self.image_previews = [
            resolve_media_url(image_derivative_reference(image, "preview"))
            for image in stored
        ]
        return self
