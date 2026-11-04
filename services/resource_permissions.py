"""Shared library visibility and ownership rules; public originals remain platform-managed."""
from fastapi import HTTPException
from tortoise.expressions import Q, Subquery

from auth.deps import AuthContext
from config import settings
from utils.messages import localized_message as msg


def owner_scope(team: int | None) -> Q:
    return Q() if team is None else Q(team_id=team)


def public_scope(prefix: str = '') -> Q:
    scope = Q(**{f'{prefix}team_id': 0})
    if settings.AUTH_ENABLED:
        from auth.models import User
        scope |= Q(**{f'{prefix}created_by__in': Subquery(User.filter(is_super_admin=True).values('id'))})
    return scope


def readable_scope(team: int | None) -> Q:
    return Q() if team is None else owner_scope(team) | public_scope()


async def resource_owner(row):
    from models.asset import Asset
    from models.novel import Novel
    return await Novel.get(id=row.novel_id) if isinstance(row, Asset) else row


async def is_public_resource(row) -> bool:
    from models.digital_human import DigitalHuman
    if isinstance(row, DigitalHuman):
        return True
    row = await resource_owner(row)
    if getattr(row, 'source', None) == 'system' or getattr(row, 'team_id', None) == 0:
        return True
    if settings.AUTH_ENABLED and getattr(row, 'created_by', None):
        from auth.models import User
        return await User.filter(id=row.created_by, is_super_admin=True).exists()
    return False


async def ensure_resource_write(ctx: AuthContext, rows) -> None:
    if not settings.AUTH_ENABLED or ctx.user is None or ctx.is_super_admin:
        return
    for row in rows:
        if await is_public_resource(row):
            raise HTTPException(403, msg('公共资源仅超级管理员可修改或删除'))
        owner = await resource_owner(row)
        if getattr(owner, 'team_id', None) != ctx.team_id:
            raise HTTPException(404, msg('资源不存在或无权访问'))
