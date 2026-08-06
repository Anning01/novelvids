from tortoise import fields

from models._base import AbstractBaseModel


class DigitalHuman(AbstractBaseModel):
    """纯数字人资源库；本项目不存储真人类型。"""

    country = fields.CharField(max_length=64, db_index=True, description="国家或地区")
    age = fields.IntField(description="年龄")
    gender = fields.CharField(max_length=32, db_index=True, description="性别")
    occupation = fields.CharField(max_length=100, db_index=True, description="职业")
    asset_id = fields.CharField(max_length=128, unique=True, description="数字人资产 ID")
    image_url = fields.CharField(max_length=500, description="数字人图片 URL")
    is_active = fields.BooleanField(default=True, db_index=True, description="是否启用")

    class Meta:
        table = "digital_humans"
