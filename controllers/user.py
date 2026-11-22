"""用户管理控制器（仅超级管理员）：列表、统计、禁用登录和删除。"""

from utils.messages import localized_message

from decimal import Decimal

from fastapi import HTTPException
from tortoise.expressions import Q
from tortoise.functions import Count, Sum
from tortoise.transactions import in_transaction
from services.team_lifecycle import archive_locked_team

from auth.security import hash_password
from auth.models import Team, TeamMember, User


class UserController:
    async def list_users(
        self, page: int, page_size: int, search: str | None = None
    ) -> dict:
        base = User.all()
        if search and search.strip():
            base = base.filter(
                Q(username__icontains=search.strip())
                | Q(nickname__icontains=search.strip())
            )
        total = await base.count()
        users = await base.order_by("id").offset((page - 1) * page_size).limit(page_size)

        costs = {
            row["user_id"]: Decimal(str(row["total"]))
            for row in await TeamMember.all()
            .group_by("user_id")
            .annotate(total=Sum("total_cost"))
            .values("user_id", "total")
        }
        team_counts = {
            row["user_id"]: row["count"]
            for row in await TeamMember.all()
            .group_by("user_id")
            .annotate(count=Count("id"))
            .values("user_id", "count")
        }
        owned = {}
        for team in await Team.filter(owner_user_id__in=[user.id for user in users]).order_by("id").values(
            "id", "name", "balance", "owner_user_id"
        ):
            owned.setdefault(team["owner_user_id"], []).append({
                "id": team["id"], "name": team["name"], "balance": format(team["balance"], "f"),
            })
        items = [
            {
                "id": user.id,
                "username": user.username,
                "nickname": user.nickname,
                "is_super_admin": user.is_super_admin,
                "status": user.status,
                "created_at": user.created_at,
                "total_cost": costs.get(user.id, Decimal("0")),
                "team_count": team_counts.get(user.id, 0),
                "owned_teams": owned.get(user.id, []),
            }
            for user in users
        ]
        pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
        }

    async def create_user(self, username: str, password: str, nickname: str) -> dict:
        username = username.strip()
        if not username:
            raise HTTPException(status_code=422, detail=localized_message('用户名不能为空'))
        if await User.filter(username=username).exists():
            raise HTTPException(status_code=400, detail=localized_message('用户名已存在'))
        user = await User.create(
            username=username,
            nickname=nickname or username,
            password_hash=hash_password(password),
        )
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "is_super_admin": False,
            "status": user.status,
            "created_at": user.created_at,
            "total_cost": Decimal("0"),
            "team_count": 0,
        }

    async def set_status(self, user_id: int, status: int, operator_id: int) -> dict:
        if user_id == operator_id:
            raise HTTPException(status_code=400, detail=localized_message('不能修改自己的登录状态'))
        user = await self._get_user(user_id)
        if user.is_super_admin:
            raise HTTPException(status_code=400, detail=localized_message('超级管理员账号不可在界面禁用'))
        user.status = status
        await user.save(update_fields=["status", "updated_at"])
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "is_super_admin": user.is_super_admin,
            "status": user.status,
            "created_at": user.created_at,
            "total_cost": await self._user_total_cost(user.id),
            "team_count": await TeamMember.filter(user=user).count(),
        }

    async def remove_user(self, user_id: int, operator_id: int, archive_team_ids: list[int] | None = None) -> None:
        if user_id == operator_id:
            raise HTTPException(status_code=400, detail=localized_message('不能删除自己'))
        async with in_transaction():
            # Team creation also locks the owner before assigning ownership.
            user = await User.filter(id=user_id).select_for_update().first()
            if user is None:
                raise HTTPException(404, localized_message("用户不存在"))
            if user.is_super_admin:
                raise HTTPException(status_code=400, detail=localized_message('超级管理员账号不可删除'))
            owned = await Team.filter(owner_user_id=user_id).select_for_update().order_by("id")
            if owned and not archive_team_ids:
                raise HTTPException(400, localized_message('该用户是团队所有人，请先解散团队，或确认解散团队并删除用户'))
            if {team.id for team in owned} != set(archive_team_ids or []):
                raise HTTPException(409, localized_message("用户拥有的团队已变更，请刷新后重新确认"))
            for team in owned:
                await archive_locked_team(team)
            await user.delete()

    async def stats(self) -> dict:
        user_count = await User.all().count()
        team_count = await Team.all().count()
        user_total_cost = Decimal("0")
        async for row in TeamMember.all().values("total_cost"):
            user_total_cost += Decimal(str(row["total_cost"] or 0))
        team_balance_total = Decimal("0")
        async for row in Team.all().values("balance"):
            team_balance_total += Decimal(str(row["balance"] or 0))
        return {
            "user_count": user_count,
            "user_total_cost": float(user_total_cost),
            "team_count": team_count,
            "team_balance_total": float(team_balance_total),
        }

    async def _get_user(self, user_id: int) -> User:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise HTTPException(status_code=404, detail=localized_message('用户不存在'))
        return user

    async def _user_total_cost(self, user_id: int) -> Decimal:
        total = Decimal("0")
        async for row in TeamMember.filter(user_id=user_id).values("total_cost"):
            total += Decimal(str(row["total_cost"] or 0))
        return total


user_controller = UserController()
