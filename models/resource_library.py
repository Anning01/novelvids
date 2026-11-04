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
    # Keep the historical table and IDs; old rows are videos by default.
    kind = fields.CharField(max_length=24, default="video", db_index=True)
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


class ResourcePlacement(AbstractBaseModel):
    """Team-local catalog metadata for existing records, without changing their IDs."""
    team_id = fields.IntField(default=0, db_index=True)
    catalog = fields.CharField(max_length=24)
    source_id = fields.IntField()
    media_resource_id = fields.IntField(null=True)
    folder_id = fields.IntField(default=0, db_index=True)
    name = fields.CharField(max_length=255, default="")

    class Meta:
        table = "resource_placements"
        unique_together = (("team_id", "catalog", "source_id"),)


class ProjectResource(AbstractBaseModel):
    novel = fields.ForeignKeyField('models.Novel', related_name='library_resources', on_delete=fields.CASCADE)
    resource_id = fields.IntField()

    class Meta:
        table = 'project_resources'
        unique_together = (('novel', 'resource_id'),)
