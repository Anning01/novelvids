"""猫影用户会话服务。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from utils.messages import localized_message
from utils.enums import UserStatusEnum

from auth.models import QilingIdentity, Team, TeamMember, User, UserSession
from auth.schemas import LoginIn, RegisterIn, LoginOut, MeOut, MembershipOut, UserOut
from auth.security import hash_password, verify_password, hash_token, new_session_token
from config import settings


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    """发放和撤销本地会话并返回团队成员身份。"""

    async def login(self, data: LoginIn) -> LoginOut:
        user = await User.get_or_none(username=data.username.strip())
        if user is None or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail=localized_message('用户名或密码错误'))
        if user.status != UserStatusEnum.active.value:
            raise HTTPException(status_code=403, detail=localized_message('账号已停用，请联系管理员'))
        return await self.issue_session(user)

    async def register(self, data: RegisterIn) -> LoginOut:
        """经邀请链接注册：创建账号、加入团队并直接登录。"""
        from services.invites import register_via_invite

        user, _ = await register_via_invite(
            data.username, data.password, data.nickname, data.invite_token
        )
        return await self.issue_session(user)

    async def issue_session(self, user: User) -> LoginOut:
        token = new_session_token()
        await UserSession.create(
            token_hash=hash_token(token),
            user=user,
            expires_at=_now() + timedelta(hours=settings.SESSION_TTL_HOURS),
        )
        return LoginOut(token=token, user=UserOut.model_validate(user))

    async def me(self, user: User) -> MeOut:
        memberships = await (
            TeamMember.filter(user=user).select_related("team").all()
        )
        total = sum(
            (item.total_cost for item in memberships),
            Decimal("0"),
        )
        return MeOut(
            user=UserOut.model_validate(user),
            memberships=[
                MembershipOut(
                    team_id=item.team_id,
                    team_name=item.team.name,
                    role=item.role,
                    status=item.status,
                    team_status=item.team.status,
                    is_owner=item.team.owner_user_id == user.id,
                    total_cost=float(item.total_cost),
                    cost_limit=(
                        float(item.cost_limit)
                        if item.cost_limit is not None
                        else None
                    ),
                    team_balance=float(item.team.balance),
                    joined_at=item.created_at,
                    member_limit=item.team.member_limit,
                )
                for item in memberships
            ],
            is_super_admin=user.is_super_admin,
            qiling_bound=await QilingIdentity.filter(user_id=user.id).exists(),
            owns_team=await Team.filter(owner_user_id=user.id).exists(),
            total_cost=float(total),
        )

    async def logout(self, token: str | None) -> None:
        if token:
            await UserSession.filter(token_hash=hash_token(token)).delete()

    async def change_password(
        self, user: User, old_password: str, new_password: str
    ) -> None:
        if not verify_password(old_password, user.password_hash):
            raise HTTPException(status_code=400, detail=localized_message('当前密码不正确'))
        user.password_hash = hash_password(new_password)
        await user.save(update_fields=["password_hash", "updated_at"])


auth_service = AuthService()
