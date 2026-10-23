"""团队视频资源。目录归属与物理存储位置独立。"""
from tortoise import fields

from models._base import AbstractBaseModel


class ResourceFolder(AbstractBaseModel):
    team_id = fields.IntField(default=0, db_index=True)
    created_by = fields.IntField(null=True)
    parent_id = fields.IntField(default=0, db_index=True)
    name = fields.CharField(max_length=100)
    deleting = fields.BooleanField(default=False)

    class Meta:
        table = "resource_folders"
        unique_together = (("team_id", "parent_id", "name"),)


class VideoResource(AbstractBaseModel):
    team_id = fields.IntField(default=0, db_index=True)
    created_by = fields.IntField(null=True)
    folder_id = fields.IntField(default=0, db_index=True)
    name = fields.CharField(max_length=255)
    filename = fields.CharField(max_length=255)
    storage_ref = fields.CharField(max_length=1000)
    poster_ref = fields.CharField(max_length=1000, default="")
    media = fields.JSONField(default=dict)
    is_source = fields.BooleanField(default=False)
    state = fields.CharField(max_length=24, default="uploading", db_index=True)

    class Meta:
        table = "video_resources"
