"""团队管理控制器：余额（见 services/balance）、成员管理、邀请链接、团队 CRUD。"""

from decimal import Decimal

from fastapi import HTTPException

from auth.models import Team, TeamMember, User
from services import balance, invites
from utils.enums import TeamRoleEnum

_ROLES = {role.value for role in TeamRoleEnum}


def _member_out(membership: TeamMember, username: str, nickname: str) -> dict:
    return {
        "user_id": membership.user_id,
        "username": username,
        "nickname": nickname,
        "role": membership.role,
        "status": membership.status,
        "total_cost": membership.total_cost,
        "cost_limit": membership.cost_limit,
    }


def _team_out(team: Team, member_count: int) -> dict:
    return {
        "id": team.id,
        "name": team.name,
        "balance": team.balance,
        "model_config_source": team.model_config_source,
        "status": team.status,
        "member_limit": team.member_limit,
        "owner_user_id": team.owner_user_id,
        "owner_username": "",
        "member_count": member_count,
        "created_at": team.created_at,
        "updated_at": team.updated_at,
    }


class TeamController:
    # ---- 余额 ----

    async def balance(self, team_id: int) -> dict:
        return {"team_id": team_id, "balance": await balance.get_balance(team_id)}

    async def top_up(
        self,
        team_id: int,
        amount: Decimal,
        operator_user_id: int | None,
        note: str,
    ) -> dict:
        result = await balance.top_up(team_id, amount, operator_user_id, note)
        return {"team_id": team_id, "balance": result}

    async def transactions(self, team_id: int, page: int, page_size: int) -> dict:
        return await balance.list_transactions(team_id, page, page_size)

    # ---- 成员 ----

    async def _ensure_team(self, team_id: int) -> Team:
        team = await Team.get_or_none(id=team_id)
        if team is None:
            raise HTTPException(status_code=404, detail="团队不存在")
        return team

    async def _get_membership(self, team_id: int, user_id: int) -> TeamMember:
        membership = await TeamMember.get_or_none(team_id=team_id, user_id=user_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="成员不存在")
        return membership

    async def members(
        self, team_id: int, page: int = 1, page_size: int = 20
    ) -> dict:
        await self._ensure_team(team_id)
        base = TeamMember.filter(team_id=team_id).select_related("user")
        total = await base.count()
        rows = await base.order_by("id").offset((page - 1) * page_size).limit(page_size)
        items = [
            _member_out(row, row.user.username, row.user.nickname) for row in rows
        ]
        pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
        }

    async def update_member(
        self,
        team_id: int,
        user_id: int,
        operator_user_id: int,
        role: str | None = None,
        status: int | None = None,
    ) -> dict:
        if role is not None and role not in _ROLES:
            raise HTTPException(status_code=422, detail="角色必须是 admin/creator/viewer")
        if status is not None and status not in (0, 1):
            raise HTTPException(status_code=422, detail="成员状态必须是 0 或 1")
        if user_id == operator_user_id:
            raise HTTPException(status_code=400, detail="不能修改自己的角色或状态")
        membership = await self._get_membership(team_id, user_id)
        update_fields = ["updated_at"]
        if role is not None:
            membership.role = role
            update_fields.append("role")
        if status is not None:
            membership.status = status
            update_fields.append("status")
        await membership.save(update_fields=update_fields)
        user = await membership.user
        return _member_out(membership, user.username, user.nickname)

    async def set_member_limit(
        self, team_id: int, user_id: int, cost_limit: Decimal | None
    ) -> dict:
        membership = await self._get_membership(team_id, user_id)
        if cost_limit is not None and cost_limit < 0:
            raise HTTPException(status_code=422, detail="限额不能为负数")
        membership.cost_limit = cost_limit
        await membership.save(update_fields=["cost_limit", "updated_at"])
        user = await membership.user
        return _member_out(membership, user.username, user.nickname)

    async def remove_member(
        self, team_id: int, user_id: int, operator_user_id: int
    ) -> None:
        if user_id == operator_user_id:
            raise HTTPException(status_code=400, detail="不能移除自己")
        membership = await self._get_membership(team_id, user_id)
        await membership.delete()

    async def reset_member_password(
        self, team_id: int, user_id: int, new_password: str
    ) -> None:
        from auth.models import User
        from auth.security import hash_password

        membership = await self._get_membership(team_id, user_id)
        user = await User.get(id=membership.user_id)
        user.password_hash = hash_password(new_password)
        await user.save(update_fields=["password_hash", "updated_at"])

    # ---- 邀请链接（成员加入的唯一方式） ----

    async def create_invite(
        self, team_id: int, role: str, created_by: int | None
    ) -> dict:
        invite = await invites.create_invite(team_id, role, created_by)
        return {
            "token": invite.token,
            "team_id": invite.team_id,
            "role": invite.role,
            "expires_at": invite.expires_at,
        }

    async def invite_info(self, token: str) -> dict:
        return await invites.get_invite_info(token)

    async def join_invite(self, token: str, user) -> dict:
        return await invites.join_team_via_invite(user, token)

    # ---- 团队（超管） ----

    async def teams(self, page: int, page_size: int) -> dict:
        query = Team.all()
        total = await query.count()
        teams = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
        owner_ids = {team.owner_user_id for team in teams if team.owner_user_id}
        owners = {
            user.id: user.username
            for user in await User.filter(id__in=list(owner_ids))
        } if owner_ids else {}
        items = []
        for team in teams:
            count = await TeamMember.filter(team=team).count()
            item = _team_out(team, count)
            item["owner_username"] = owners.get(team.owner_user_id, "")
            items.append(item)
        pages = (total + page_size - 1) // page_size if total else 0
        return {
            "items": items,
            "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
        }

    async def create_team(
        self,
        name: str,
        owner_user_id: int,
        member_limit: int | None = None,
    ) -> Team:
        name = name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="团队名称不能为空")
        if await Team.filter(name=name).exists():
            raise HTTPException(status_code=400, detail="团队名称已存在")
        if member_limit is not None and member_limit < 1:
            raise HTTPException(status_code=422, detail="人员上限必须为正整数")
        owner = await User.get_or_none(id=owner_user_id)
        if owner is None:
            raise HTTPException(status_code=404, detail="所有人用户不存在")
        team = await Team.create(
            name=name,
            member_limit=member_limit,
            owner_user_id=owner.id,
        )
        # 所有人自动成为该团队管理员
        await TeamMember.create(
            team=team, user=owner, role=TeamRoleEnum.admin.value
        )
        return team

    async def update_team(
        self,
        team_id: int,
        name: str | None,
        status: int | None,
        member_limit: int | None = None,
    ) -> dict:
        team = await self._ensure_team(team_id)
        update_fields = ["updated_at"]
        if name is not None:
            name = name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="团队名称不能为空")
            duplicated = await Team.filter(name=name).exclude(id=team_id).exists()
            if duplicated:
                raise HTTPException(status_code=400, detail="团队名称已存在")
            team.name = name
            update_fields.append("name")
        if status is not None:
            if status not in (0, 1):
                raise HTTPException(status_code=422, detail="团队状态必须是 0 或 1")
            team.status = status
            update_fields.append("status")
        if member_limit is not None:
            if member_limit < 1:
                raise HTTPException(status_code=422, detail="人员上限必须为正整数")
            team.member_limit = member_limit
            update_fields.append("member_limit")
        await team.save(update_fields=update_fields)
        count = await TeamMember.filter(team=team).count()
        return _team_out(team, count)


team_controller = TeamController()
