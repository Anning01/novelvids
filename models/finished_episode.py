"""Visibility settings for one explicitly published episode version."""
from tortoise import fields

from models._base import AbstractBaseModel


class FinishedEpisodePublication(AbstractBaseModel):
    chapter = fields.OneToOneField('models.Chapter', related_name='finished_publication', on_delete=fields.CASCADE)
    export = fields.ForeignKeyField('models.ChapterExport', null=True, on_delete=fields.SET_NULL, related_name='publications')
    featured = fields.BooleanField(default=False, db_index=True)

    class Meta:
        table = 'finished_episode_publications'
