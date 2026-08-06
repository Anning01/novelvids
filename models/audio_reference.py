from tortoise import fields

from models._base import AbstractBaseModel


class AudioReference(AbstractBaseModel):
    """可复用的参考音频资源。"""

    nickname = fields.CharField(max_length=100, db_index=True, description="昵称")
    gender = fields.CharField(max_length=32, db_index=True, description="性别")
    audio_url = fields.CharField(max_length=500, description="音频 URL")
    avatar_url = fields.CharField(max_length=500, description="头像 URL")
    asset_id = fields.CharField(max_length=128, unique=True, description="音频资产 ID")
    is_active = fields.BooleanField(default=True, db_index=True, description="是否启用")

    class Meta:
        table = "audio_references"
