"""Transfer a dedicated platform account to an existing, verified local account."""

from tortoise.transactions import in_transaction

from auth.models import QilingIdentity, Team, TeamMember, User, UserSession


async def consolidate_platform_account(source_id: int | None, target_id: int) -> None:
    if source_id == target_id:
        raise ValueError("Source and target must be different accounts")
    async with in_transaction():
        if source_id is None:
            # Serialize first-admin setup against another invocation on the same database.
            await User.all().order_by("id").select_for_update().first()
            if await User.filter(is_super_admin=True, status=1).exists():
                raise ValueError("An active administrator exists. Specify the account to transfer")
        user_ids = [target_id] if source_id is None else [source_id, target_id]
        users = await User.filter(id__in=user_ids).order_by("id").select_for_update()
        accounts = {user.id: user for user in users}
        source = accounts.get(source_id)
        target = accounts.get(target_id)
        if not target or target.is_super_admin or (source_id is not None and (not source or not source.is_super_admin)):
            raise ValueError("Expected a platform administrator and a separate regular account")
        if target.status != 1 or (source and source.status != 1):
            raise ValueError("The selected accounts must be active")
        if not await QilingIdentity.filter(user_id=target.id).exclude(issuer="").exists():
            raise ValueError("The receiving account must first bind and verify its Qiling identity")
        if source and (await Team.filter(owner_user_id=source.id).exists() or await TeamMember.filter(user_id=source.id).exists()):
            raise ValueError("The source account has team access that must be handled separately")

        # Preserve the source ID so historical operations retain their attribution.
        target.is_super_admin = True
        await target.save(update_fields=["is_super_admin", "updated_at"])
        if source:
            source.is_super_admin = False
            source.status = 0
            await source.save(update_fields=["is_super_admin", "status", "updated_at"])
        await UserSession.filter(user_id__in=user_ids).delete()
