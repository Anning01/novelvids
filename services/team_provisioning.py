"""Create an owned team and its administrator membership atomically."""

from itertools import count

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from auth.models import Team, TeamMember, User
from utils.enums import TeamRoleEnum
from utils.messages import localized_message as msg


DEFAULT_TEAM_MEMBER_LIMIT = 3


async def create_owned_team(
    owner_id: int,
    name: str | None = None,
    member_limit: int | None = DEFAULT_TEAM_MEMBER_LIMIT,
) -> Team:
    try:
        async with in_transaction():
            owner = await User.filter(id=owner_id).select_for_update().first()
            if owner is None:
                raise HTTPException(404, msg("所有人用户不存在"))
            existing = await Team.filter(owner_user_id=owner.id).first()
            if existing:
                if name is None:
                    return existing
                raise HTTPException(409, msg("每个账号只能创建一个团队"))

            limit = DEFAULT_TEAM_MEMBER_LIMIT if member_limit is None and name is None else member_limit
            if name is None:
                team = await _default_team(owner, member_limit=limit)
            else:
                if await Team.filter(name=name).exists():
                    raise HTTPException(400, msg("团队名称已存在"))
                team = await Team.create(name=name, member_limit=limit, owner_user_id=owner.id)
            await TeamMember.create(team=team, user=owner, role=TeamRoleEnum.admin.value)
            return team
    except IntegrityError:
        raise HTTPException(409, msg("团队名称已存在")) from None


async def _default_team(owner: User, member_limit: int | None = DEFAULT_TEAM_MEMBER_LIMIT) -> Team:
    label = (owner.nickname or "").strip()
    if not label:
        label = "我的团队"
    else:
        label += "的团队"
    for number in count():
        suffix = "" if number == 0 else f" ({number + 1})"
        name = label[:100 - len(suffix)] + suffix
        team, created = await Team.get_or_create(
            name=name,
            defaults={
                "owner_user_id": owner.id,
                "member_limit": DEFAULT_TEAM_MEMBER_LIMIT if member_limit is None else member_limit,
            },
        )
        if created:
            return team
