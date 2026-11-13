"""Developer keys authorize external model requests within the issuing user's team."""
from datetime import datetime, timezone
import secrets

from fastapi import Depends, HTTPException, Request
from auth.deps import AuthContext, context_for_team, require_roles
from auth.models import PlatformApiKey, StudioKeyGrant, Team
from tortoise.transactions import in_transaction
from auth.security import hash_token
from utils.enums import UserStatusEnum


async def console_owner(ctx: AuthContext = Depends(require_roles("admin", "creator"))) -> AuthContext:
    if not ctx.user or not ctx.team_id or not await Team.filter(id=ctx.team_id, status=1).exists():
        raise HTTPException(403, "请选择可用团队")
    return ctx


def key_view(row):
    return {"id": row.id, "name": row.name, "preview": row.preview, "created_at": row.created_at}


async def create_key(ctx, name, *, studio=False):
    raw = "nv_" + secrets.token_urlsafe(32)
    async with in_transaction() as db:
        row = await PlatformApiKey.create(using_db=db, user_id=ctx.user.id, team_id=ctx.team_id, name=name,
                                          token_hash=hash_token(raw), preview=raw[:7] + "…" + raw[-4:])
        if studio:
            await StudioKeyGrant.create(using_db=db, key=row)
    return {**key_view(row), "key": raw, "purpose":"studio" if studio else "api"}


async def revoke_key(ctx, key_id):
    updated = await PlatformApiKey.filter(id=key_id, user_id=ctx.user.id, team_id=ctx.team_id,
        revoked_at__isnull=True).update(revoked_at=datetime.now(timezone.utc))
    if not updated:
        raise HTTPException(404, "API Key 不存在")


async def developer_identity(request: Request) -> AuthContext:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not value.startswith("nv_") or len(value) > 128:
        raise HTTPException(401, "需要有效的 API Key", headers={"WWW-Authenticate": "Bearer"})
    row = await PlatformApiKey.get_or_none(token_hash=hash_token(value), revoked_at__isnull=True).select_related("user", "team")
    if not row:
        raise HTTPException(401, "API Key 无效或已撤销", headers={"WWW-Authenticate": "Bearer"})
    if row.user.status != UserStatusEnum.active.value or row.team.status != 1:
        raise HTTPException(403, "账户或团队已停用")
    request.state.platform_key_id = row.id
    ctx = await context_for_team(row.user, row.team_id)
    ctx.platform_key_id = row.id
    if not ctx.is_super_admin and (not ctx.membership or ctx.membership.role not in {"admin", "creator"}):
        raise HTTPException(403, "当前团队角色不能调用模型")
    return ctx


async def studio_identity(request: Request, ctx: AuthContext = Depends(developer_identity)):
    if not await StudioKeyGrant.filter(key_id=request.state.platform_key_id).exists():
        raise HTTPException(403, "此密钥未授权本地猫影")
    return ctx
