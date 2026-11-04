"""Additive editor records; source scenes and media are never modified by edits."""
from tortoise import fields
from models._base import AbstractBaseModel


class ChapterEditDraft(AbstractBaseModel):
    chapter = fields.OneToOneField('models.Chapter', related_name='edit_draft', on_delete=fields.CASCADE)
    revision = fields.IntField(default=1)
    document = fields.JSONField(default=dict)
    updated_by = fields.IntField(null=True)

    class Meta:
        table = 'chapter_edit_drafts'


class EditorAsset(AbstractBaseModel):
    novel = fields.ForeignKeyField('models.Novel', related_name='editor_assets', on_delete=fields.CASCADE)
    team_id = fields.IntField(null=True, db_index=True)
    created_by = fields.IntField(null=True)
    kind = fields.CharField(max_length=16)
    name = fields.CharField(max_length=255)
    media_ref = fields.TextField()
    poster_ref = fields.TextField(null=True)
    sha256 = fields.CharField(max_length=64)
    probe = fields.JSONField(default=dict)
    size_bytes = fields.BigIntField(default=0)

    class Meta:
        table = 'editor_assets'
