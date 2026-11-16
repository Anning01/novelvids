"""Private creative methods, separate from platform output contracts."""

from tortoise import fields
from models._base import AbstractBaseModel


class UserSkill(AbstractBaseModel):
    # Owner 0 is the local workspace when login is disabled.
    owner_id = fields.IntField(db_index=True)
    task = fields.CharField(max_length=24)
    name = fields.CharField(max_length=100)
    description = fields.CharField(max_length=1000, default='')
    instructions = fields.TextField()
    references = fields.JSONField(default=list)
    version = fields.IntField(default=1)
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = 'user_skills'


class TaskSkillPreference(AbstractBaseModel):
    owner_id = fields.IntField()
    task = fields.CharField(max_length=24)
    skill_id = fields.IntField(default=0)

    class Meta:
        table = 'task_skill_preferences'
        unique_together = (('owner_id', 'task'),)
