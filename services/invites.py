"""团队邀请服务：生成/校验/加入/经邀请注册。

规则：
- 邀请链接 24 小时有效，可多人使用；
- 成员加入团队的唯一方式（管理员不再直接建号）；
- 加入与注册都校验团队人数上限与团队状态。
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from auth.models import Team, TeamInvite, TeamMember, User
from auth.security import hash_password

INVITE_TTL_HOURS = 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_invite(
    team_id: int, role: str, created_by: int | None = None
) -> TeamInvite:
    team = await Team.get_or_none(id=team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="团队不存在")
    if role not in ("admin", "creator", "viewer"):
        raise HTTPException(status_code=422, detail="角色必须是 admin/creator/viewer")
    token = secrets.token_urlsafe(24)
    return await TeamInvite.create(
        token=token,
        team=team,
        role=role,
        created_by=created_by,
        expires_at=_now() + timedelta(hours=INVITE_TTL_HOURS),
    )


async def get_invite_info(token: str) -> dict:
    """公开信息：供邀请页展示（不要求登录）。"""
    invite = await _valid_invite(token)
    return {
        "token": invite.token,
        "team_id": invite.team_id,
        "team_name": invite.team.name,
        "role": invite.role,
        "expires_at": invite.expires_at,
    }


async def join_team_via_invite(user: User, token: str) -> dict:
    """老用户经邀请链接加入团队。"""
    invite = await _valid_invite(token)
    await _enforce_member_limit(invite.team)
    if await TeamMember.filter(team=invite.team, user=user).exists():
        raise HTTPException(status_code=400, detail="你已是该团队成员")
    membership = await TeamMember.create(team=invite.team, user=user, role=invite.role)
    invite.used_count += 1
    await invite.save(update_fields=["used_count", "updated_at"])
    return {
        "team_id": invite.team_id,
        "team_name": invite.team.name,
        "role": membership.role,
        "expires_at": invite.expires_at,
    }


async def register_via_invite(
    username: str, password: str, nickname: str, token: str
) -> tuple[User, dict]:
    """新用户经邀请链接注册并自动加入团队。"""
    invite = await _valid_invite(token)
    username = username.strip()
    if await User.filter(username=username).exists():
        raise HTTPException(status_code=400, detail="用户名已被使用")
    await _enforce_member_limit(invite.team)
    user = await User.create(
        username=username,
        nickname=nickname or username,
        password_hash=hash_password(password),
    )
    membership = await TeamMember.create(
        team=invite.team, user=user, role=invite.role
    )
    invite.used_count += 1
    await invite.save(update_fields=["used_count", "updated_at"])
    return user, {
        "team_id": invite.team_id,
        "team_name": invite.team.name,
        "role": membership.role,
    }


async def _valid_invite(token: str) -> TeamInvite:
    invite = await TeamInvite.get_or_none(token=token).select_related("team")
    if invite is None or invite.expires_at <= _now():
        raise HTTPException(status_code=404, detail="邀请链接不存在或已过期")
    if invite.team.status != 1:
        raise HTTPException(status_code=403, detail="团队已停用")
    return invite


async def _enforce_member_limit(team: Team) -> None:
    if team.member_limit is None:
        return
    count = await TeamMember.filter(team=team).count()
    if count >= team.member_limit:
        raise HTTPException(
            status_code=403, detail=f"团队人数已达上限（{team.member_limit} 人）"
        )
