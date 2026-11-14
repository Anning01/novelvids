"""Browser consent for a stdio process sharing the installation's database."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from auth.deps import AuthContext, context_for_team, require_roles
from auth.models import LocalMcpConnection, Team, UserSession
from auth.security import hash_token
from utils.enums import UserStatusEnum


class ConnectionRequired(ValueError):
    def __init__(self, url: str):
        self.url = url
        super().__init__("请在猫影确认连接和目标团队，再重试。")


class LocalMcpAccess:
    def __init__(self, app_url):
        self.app_url = app_url.rstrip("/")
        self.code = None

    async def authorize(self, *, writing: bool):
        now = datetime.now(timezone.utc)
        row = await LocalMcpConnection.get_or_none(code=self.code).select_related("session__user", "team") if self.code else None
        if not row or row.expires_at <= now:
            await LocalMcpConnection.filter(expires_at__lte=now).delete()
            self.code = uuid4()
            row = await LocalMcpConnection.create(code=self.code, expires_at=now + timedelta(minutes=15))
        if not row.session_id:
            raise ConnectionRequired(f"{self.app_url}/#/mcp/connect/{self.code}")
        if row.session.expires_at <= now or row.session.user.status != UserStatusEnum.active or row.team.status != 1:
            raise HTTPException(403, "当前登录或团队已失效")
        ctx = await context_for_team(row.session.user, row.team_id)
        if writing:
            await require_roles("admin", "creator")(ctx)
        return ctx


async def approve(code: UUID, bearer: str, ctx: AuthContext):
    now = datetime.now(timezone.utc)
    if not ctx.user or not ctx.team_id or not await Team.filter(id=ctx.team_id, status=1).exists():
        raise HTTPException(403, "请选择可用团队")
    session = await UserSession.get_or_none(token_hash=hash_token(bearer), user_id=ctx.user.id, expires_at__gt=now)
    if not session:
        raise HTTPException(401, "登录已失效")
    changed = await LocalMcpConnection.filter(code=code, session_id=None, expires_at__gt=now).update(
        session_id=session.id, team_id=ctx.team_id, expires_at=session.expires_at)
    if not changed:
        raise HTTPException(409, "连接请求已使用或已过期")
