"""Durable operation receipts; external submissions are never replayed blindly."""

from tortoise import fields
from models._base import AbstractBaseModel


class AgentOperation(AbstractBaseModel):
    task = fields.ForeignKeyField(
        "models.AiTask", related_name="operations", on_delete=fields.CASCADE
    )
    key = fields.CharField(max_length=200)
    state = fields.CharField(max_length=24, default="pending")
    result = fields.JSONField(default=dict)
    external = fields.BooleanField(default=False)

    class Meta:
        table = "agent_operations"
        unique_together = (("task", "key"),)
