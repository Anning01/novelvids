"""Durable field-level changes made by the creation assistant."""

from tortoise import fields

from models._base import AbstractBaseModel


class AgentSettings(AbstractBaseModel):
    configuration = fields.JSONField(default=dict)

    class Meta:
        table = "creation_agent_settings"


class AgentConversation(AbstractBaseModel):
    novel = fields.ForeignKeyField("models.Novel", related_name="agent_conversations", on_delete=fields.CASCADE)
    created_by = fields.IntField(null=True, db_index=True)
    team_id = fields.IntField(null=True)
    active_task_id = fields.UUIDField(null=True)
    summary = fields.TextField(default="")
    summary_until_id = fields.IntField(default=0)

    class Meta:
        table = "creation_agent_conversations"


class AgentMessage(AbstractBaseModel):
    conversation = fields.ForeignKeyField("models.AgentConversation", related_name="messages", on_delete=fields.CASCADE)
    task = fields.ForeignKeyField("models.AiTask", related_name="agent_messages", on_delete=fields.CASCADE)
    request_id = fields.UUIDField()
    request_hash = fields.CharField(max_length=64)
    role = fields.CharField(max_length=16)
    content = fields.TextField(default="")
    run_input = fields.JSONField(default=dict)
    native_messages = fields.JSONField(default=list)
    events = fields.JSONField(default=list)
    usage = fields.JSONField(default=dict)
    model_snapshot = fields.JSONField(default=dict)
    billing_record_id = fields.IntField(null=True)

    class Meta:
        table = "creation_agent_messages"
        unique_together = (("conversation", "request_id", "role"), ("task", "role"))


class PromptChange(AbstractBaseModel):
    novel = fields.ForeignKeyField("models.Novel", related_name="prompt_changes", on_delete=fields.CASCADE)
    task = fields.ForeignKeyField("models.AiTask", related_name="prompt_changes", on_delete=fields.CASCADE)
    tool_call_id = fields.CharField(max_length=200)
    request_hash = fields.CharField(max_length=64)
    changes = fields.JSONField(default=list)
    reverted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "creation_prompt_changes"
        unique_together = (("task", "tool_call_id"),)


class CreationConstraint(AbstractBaseModel):
    novel = fields.ForeignKeyField("models.Novel", related_name="creation_constraints", on_delete=fields.CASCADE)
    source_message = fields.ForeignKeyField("models.AgentMessage", related_name="creation_constraints", on_delete=fields.CASCADE)
    fingerprint = fields.CharField(max_length=64)
    content = fields.TextField()
    source_quote = fields.TextField()
    scope = fields.JSONField(default=dict)
    supersedes_id = fields.IntField(null=True)
    superseded_by_id = fields.IntField(null=True)

    class Meta:
        table = "creation_agent_constraints"
        unique_together = (("source_message", "fingerprint"),)
