"""Reviewed story facts are independent of conversations and visual assets."""

from tortoise import fields
from models._base import AbstractBaseModel


class StoryMemoryProject(AbstractBaseModel):
    """Provenance for a novel that was successfully split into multiple chapters."""

    novel = fields.OneToOneField('models.Novel', related_name='automatic_story_memory', on_delete=fields.CASCADE)

    class Meta:
        table = 'story_memory_projects'


class StorySubject(AbstractBaseModel):
    novel = fields.ForeignKeyField('models.Novel', related_name='story_subjects', on_delete=fields.CASCADE)
    kind = fields.CharField(max_length=24)
    name = fields.CharField(max_length=100)
    aliases = fields.JSONField(default=list)

    class Meta:
        table = 'story_subjects'
        unique_together = (('novel', 'kind', 'name'),)


class StoryCommit(AbstractBaseModel):
    novel = fields.ForeignKeyField('models.Novel', related_name='story_commits', on_delete=fields.CASCADE)
    chapter = fields.ForeignKeyField('models.Chapter', null=True, related_name='story_commits', on_delete=fields.RESTRICT)
    request_id = fields.UUIDField()
    request_spec = fields.JSONField(default=dict)
    task = fields.ForeignKeyField('models.AiTask', null=True, related_name='story_commits', on_delete=fields.SET_NULL)
    parent_id = fields.IntField(null=True)
    replaces_id = fields.IntField(null=True)
    source_hash = fields.CharField(max_length=64)
    source_snapshot = fields.JSONField(default=dict)
    status = fields.CharField(max_length=24, default='pending')
    revision = fields.IntField(default=1)
    candidate = fields.JSONField(default=dict)
    review = fields.JSONField(default=dict)
    package_hash = fields.CharField(max_length=64, default='')
    created_by = fields.IntField(null=True)
    decided_by = fields.IntField(null=True)
    decision = fields.TextField(default='')
    decided_at = fields.DatetimeField(null=True)

    class Meta:
        table = 'story_commits'
        unique_together = (('novel', 'request_id'),)


class StoryFact(AbstractBaseModel):
    novel = fields.ForeignKeyField('models.Novel', related_name='story_facts', on_delete=fields.CASCADE)
    commit = fields.ForeignKeyField('models.StoryCommit', related_name='facts', on_delete=fields.CASCADE)
    subject = fields.ForeignKeyField('models.StorySubject', related_name='facts', on_delete=fields.RESTRICT)
    category = fields.CharField(max_length=24)
    nature = fields.CharField(max_length=24)
    content = fields.TextField()
    scope = fields.JSONField(default=dict)
    evidence = fields.JSONField(default=list)
    replaces_id = fields.IntField(null=True)
    operation = fields.CharField(max_length=16)

    class Meta:
        table = 'story_facts'
        indexes = (('novel', 'subject'), ('novel', 'category'))


class StorySnapshot(AbstractBaseModel):
    novel = fields.ForeignKeyField('models.Novel', related_name='story_snapshots', on_delete=fields.CASCADE)
    commit = fields.OneToOneField('models.StoryCommit', related_name='snapshot', on_delete=fields.CASCADE)
    data = fields.JSONField(default=dict)

    class Meta:
        table = 'story_snapshots'
