"""Project-level archive and the exact episode versions approved for public viewing."""
from tortoise import fields

from models._base import AbstractBaseModel


class PortfolioWork(AbstractBaseModel):
    novel = fields.OneToOneField('models.Novel', related_name='portfolio_work', on_delete=fields.CASCADE)
    title = fields.CharField(max_length=255)
    description = fields.TextField(default='')
    category = fields.CharField(max_length=80, default='')
    tags = fields.JSONField(default=list)
    cover_chapter_id = fields.IntField(null=True)
    status = fields.CharField(max_length=16, default='private')
    featured = fields.BooleanField(default=False)
    featured_order = fields.IntField(default=0)
    revision = fields.IntField(default=1)
    last_action = fields.CharField(max_length=16, default='archive')

    class Meta:
        table = 'portfolio_works'


class PortfolioEpisode(AbstractBaseModel):
    work = fields.ForeignKeyField('models.PortfolioWork', related_name='public_episodes', on_delete=fields.CASCADE)
    chapter = fields.ForeignKeyField('models.Chapter', related_name='portfolio_episodes', on_delete=fields.CASCADE)
    export = fields.ForeignKeyField('models.ChapterExport', related_name='portfolio_episodes', on_delete=fields.CASCADE)

    class Meta:
        table = 'portfolio_episodes'
        unique_together = (('work', 'chapter'),)
