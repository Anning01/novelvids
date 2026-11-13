from tortoise import fields

from models._base import AbstractBaseModel


class StudioCall(AbstractBaseModel):
    """One outgoing platform request and the local charge frozen before submission."""

    request_key = fields.UUIDField(unique=True)
    platform_request_id = fields.UUIDField(null=True)
    usage_record_id = fields.IntField(unique=True)
    message_id = fields.IntField(null=True, db_index=True)
    model_config_id = fields.IntField()
    base_url = fields.CharField(max_length=500)
    billing_mode = fields.CharField(max_length=16)
    multiplier = fields.DecimalField(max_digits=12, decimal_places=6)
    local_pricing = fields.JSONField(null=True)
    state = fields.CharField(max_length=16, default="pending", db_index=True)
    next_check_at = fields.DatetimeField(db_index=True)

    class Meta:
        table = "studio_calls"
