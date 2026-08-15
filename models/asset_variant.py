from typing import TYPE_CHECKING

from tortoise import fields

from models._base import AbstractBaseModel

if TYPE_CHECKING:
    from models.asset import Asset


class AssetVariant(AbstractBaseModel):
    """资产在不同章节中的视觉形态，例如人物变装、场景升级或道具变形。"""

    asset: fields.ForeignKeyRelation["Asset"] = fields.ForeignKeyField(
        "models.Asset",
        related_name="variants",
        on_delete=fields.CASCADE,
        description="所属标准资产",
    )
    name = fields.CharField(max_length=100, description="形态名称")
    description = fields.TextField(null=True, description="该形态的中文描述")
    base_traits = fields.TextField(
        null=True,
        description="该形态用户可编辑并最终发送的完整生图提示词",
    )
    chapter_numbers = fields.JSONField(default=list, description="适用章节序号")
    images = fields.JSONField(default=list, description="该形态的多张参考图")
    metadata = fields.JSONField(default=dict, description="扩展生成参数")

    class Meta:
        table = "asset_variants"
        unique_together = (("asset", "name"),)
