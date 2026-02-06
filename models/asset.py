
from typing import TYPE_CHECKING
from models._base import AbstractBaseModel
from tortoise import fields

from utils.enums import ImageSourceEnum


if TYPE_CHECKING:
    from models.novel import Novel
    
class Asset(AbstractBaseModel):
    """通用资产模型 - 人物/场景/物品。

    统一管理所有类型的资产，支持：
    - 三种类型：person（人物）、scene（场景）、item（物品）
    - 图片资产：主图 + 2张可选角度图
    - AI 生成或用户上传
    - 全局资产或单章资产
    """

    novel: fields.ForeignKeyRelation["Novel"] = fields.ForeignKeyField(
        "models.Novel",
        related_name="assets",
        on_delete=fields.CASCADE,
        description="所属小说/剧本"
    )
    asset_type = fields.IntField(db_index=True, description="资产类型")
    canonical_name = fields.CharField(max_length=100, db_index=True, description="资产名称")
    aliases = fields.JSONField(default=list, description="别名列表")  # 别名列表 ["张三", "小张"]

    # 描述信息
    description = fields.TextField(null=True, description="详细描述")  # 详细描述 (中文)
    base_traits = fields.TextField(null=True, description="英文prompt")  # 固有特征 (英文, 用于 prompt)

    # 图片资产
    main_image = fields.CharField(max_length=500, null=True, description="三视主图")  # 主图路径/URL
    angle_image_1 = fields.CharField(max_length=500, null=True, description="可选参考图1")  # 角度图1
    angle_image_2 = fields.CharField(max_length=500, null=True, description="可选参考图2")  # 角度图2
    image_source = fields.IntField(default=ImageSourceEnum.ai.value, description="图片来源")

    # 状态追踪
    is_global = fields.BooleanField(default=True, description="是否全局资产")  # 是否全局资产
    source_chapters = fields.JSONField(default=list, description="出现的章节列表")  # 出现的章节列表 [1, 3, 5]
    last_updated_chapter = fields.IntField(default=0, description="出现最新章节")

    # 元数据
    metadata = fields.JSONField(default=dict, description="元数据")


    class Meta:
        table = "assets"
        unique_together = (("novel", "asset_type", "canonical_name"),)



