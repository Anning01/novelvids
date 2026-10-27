"""Unique client operations; receipt creation and task admission share one transaction."""

from tortoise import fields
from models._base import AbstractBaseModel


class AgentSubmission(AbstractBaseModel):
    key = fields.CharField(max_length=64, unique=True)
    request_hash = fields.CharField(max_length=64)
    task_type = fields.IntField()
    task = fields.ForeignKeyField(
        "models.AiTask",
        null=True,
        related_name="submissions",
        on_delete=fields.SET_NULL,
    )

    class Meta:
        table = "agent_submissions"
