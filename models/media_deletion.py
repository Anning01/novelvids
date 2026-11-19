"""Storage work recorded atomically with permanent creative record deletion."""

from tortoise import fields

from models._base import AbstractBaseModel


class MediaDeletion(AbstractBaseModel):
    reference = fields.CharField(max_length=1000, unique=True)

    class Meta:
        table = "media_deletions"
