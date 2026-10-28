"""Immutable export artifacts; AiTask remains the only execution state machine."""

from tortoise import fields

from models._base import AbstractBaseModel


class ChapterExport(AbstractBaseModel):
    novel_id = fields.IntField(db_index=True)
    chapter_id = fields.IntField(db_index=True)
    source_video_id = fields.IntField(null=True, db_index=True)
    team_id = fields.IntField(null=True, db_index=True)
    created_by = fields.IntField(null=True)
    parent_export_id = fields.IntField(null=True, db_index=True)
    identity_key = fields.CharField(max_length=64, unique=True)
    source_version = fields.CharField(max_length=64)
    manifest = fields.JSONField(default=list)
    source_media_ref = fields.TextField(null=True)
    source_sha256 = fields.CharField(max_length=64, null=True)
    source_probe = fields.JSONField(default=dict)
    recipe = fields.JSONField(default=dict)
    media_ref = fields.TextField(null=True)
    media_sha256 = fields.CharField(max_length=64, null=True)
    output_probe = fields.JSONField(default=dict)
    provider_task_id = fields.CharField(max_length=200, null=True)
    provider_result = fields.JSONField(default=dict)
    collection_complete = fields.BooleanField(default=False, db_index=True)
    submission_slot = fields.BooleanField(default=False, db_index=True)
    collection_owner = fields.UUIDField(null=True)
    collection_lease_until = fields.DatetimeField(null=True)
    task = fields.ForeignKeyField('models.AiTask', null=True, on_delete=fields.SET_NULL, related_name='chapter_exports')

    class Meta:
        table = 'chapter_exports'
        indexes = (('novel_id', 'chapter_id'),)
