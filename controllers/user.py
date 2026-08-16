"""用户管理控制器（仅超级管理员）：列表/统计/手动创建/禁用登录/删除。"""

from decimal import Decimal

from fastapi import HTTPException
from tortoise.expressions import Q
from tortoise.functions import Count, Sum

from auth.models import Team, TeamMember, User
from auth.security import hash_password


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
            raise HTTPException(status_code=422, detail="用户名不能为空")
        if await User.filter(username=username).exists():
            raise HTTPException(status_code=400, detail="用户名已存在")
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
            raise HTTPException(status_code=400, detail="不能修改自己的登录状态")
        user = await self._get_user(user_id)
        if user.is_super_admin:
            raise HTTPException(status_code=400, detail="超级管理员账号不可在界面禁用")
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

    async def remove_user(self, user_id: int, operator_id: int) -> None:
        if user_id == operator_id:
            raise HTTPException(status_code=400, detail="不能删除自己")
        user = await self._get_user(user_id)
        if user.is_super_admin:
            raise HTTPException(status_code=400, detail="超级管理员账号不可删除")
        if await Team.filter(owner_user_id=user.id).exists():
            raise HTTPException(
                status_code=400, detail="该用户是团队所有人，请先转移或删除其团队"
            )
        await user.delete()  # 级联删除成员关系与会话

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
            raise HTTPException(status_code=404, detail="用户不存在")
        return user

    async def _user_total_cost(self, user_id: int) -> Decimal:
        total = Decimal("0")
        async for row in TeamMember.filter(user_id=user_id).values("total_cost"):
            total += Decimal(str(row["total_cost"] or 0))
        return total


user_controller = UserController()
