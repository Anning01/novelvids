"""Archive a team while retaining its identity, work and financial history."""
from fastapi import HTTPException
from tortoise.timezone import now
from tortoise.transactions import in_transaction

from auth.models import LocalMcpConnection, PlatformApiKey, Team, TeamInvite, TeamMember
from utils.messages import localized_message


ARCHIVED_TEAM_STATUS = 2


def require_unarchived(team: Team) -> None:
    if team.status == ARCHIVED_TEAM_STATUS:
        raise HTTPException(409, localized_message("团队已归档"))


async def archive_locked_team(team: Team) -> None:
    """The caller holds the team row lock and transaction."""
    if team.status == ARCHIVED_TEAM_STATUS:
        return
    team.status = ARCHIVED_TEAM_STATUS
    team.owner_user_id = None
    await team.save(update_fields=["status", "owner_user_id", "updated_at"])
    await TeamInvite.filter(team_id=team.id).delete()
    await PlatformApiKey.filter(team_id=team.id, revoked_at=None).update(revoked_at=now())
    await LocalMcpConnection.filter(team_id=team.id).delete()
    await TeamMember.filter(team_id=team.id).delete()


async def archive_team(team_id: int) -> None:
    async with in_transaction():
        team = await Team.filter(id=team_id).select_for_update().first()
        if team is None:
            raise HTTPException(404, localized_message("团队不存在"))
        await archive_locked_team(team)
