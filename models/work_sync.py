"""Local package identity and durable idempotency; application rows stay canonical."""
from tortoise import fields
from models._base import AbstractBaseModel


class WorkSyncObject(AbstractBaseModel):
    work_id = fields.CharField(max_length=120)
    episode_id = fields.CharField(max_length=120, default='')
    kind = fields.CharField(max_length=20)
    stable_id = fields.CharField(max_length=120)
    local_id = fields.IntField()
    payload = fields.JSONField(default=dict)

    class Meta:
        table = 'work_sync_objects'
        unique_together = (('work_id', 'episode_id', 'kind', 'stable_id'),)


class WorkSyncRequest(AbstractBaseModel):
    request_id = fields.CharField(max_length=120, unique=True)
    payload_hash = fields.CharField(max_length=64)
    receipt = fields.JSONField()

    class Meta:
        table = 'work_sync_requests'
