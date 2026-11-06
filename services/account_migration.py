"""Consolidate and migrate historical accounts (e.g. admin and testuser) into a target account (e.g. Qiling account)."""

from typing import Any
from tortoise.transactions import in_transaction

from auth.models import BalanceTransaction, QilingLoginAttempt, Team, TeamInvite, TeamMember, User, UserSession
from models.audio_reference import AudioReference
from models.chapter_export import ChapterExport
from models.creation_agent import AgentConversation
from models.video_edit import EditorAsset
from models.novel import Novel
from models.remake_source import RemakeSource
from models.remake_upload import RemakeUpload
from models.resource_library import ResourceFolder, VideoResource
from models.usage_record import ModelUsageRecord


async def get_consolidation_preview(source_ids: list[int], target_id: int) -> dict[str, Any]:
    """Inspect and count records that will be migrated without making modifications."""
    target = await User.filter(id=target_id).first()
    if not target:
        raise ValueError(f"Target user ID {target_id} does not exist")

    sources = await User.filter(id__in=source_ids).all()
    found_source_ids = {s.id for s in sources}
    missing = set(source_ids) - found_source_ids
    if missing:
        raise ValueError(f"Source user IDs not found: {missing}")

    if target_id in found_source_ids:
        raise ValueError("Target user ID cannot be one of the source user IDs")

    source_names = [f"{s.username} (id={s.id}, nickname={s.nickname})" for s in sources]
    has_super_admin = any(s.is_super_admin for s in sources)

    preview = {
        "target": f"{target.username} (id={target.id}, nickname={target.nickname})",
        "target_is_super_admin_before": target.is_super_admin,
        "target_will_become_super_admin": target.is_super_admin or has_super_admin,
        "sources": source_names,
        "records_to_migrate": {
            "teams_owned": await Team.filter(owner_user_id__in=source_ids).count(),
            "team_members": await TeamMember.filter(user_id__in=source_ids).count(),
            "novels": await Novel.filter(created_by__in=source_ids).count(),
            "model_usage_records": await ModelUsageRecord.filter(user_id__in=source_ids).count(),
            "audio_references": await AudioReference.filter(created_by__in=source_ids).count(),
            "video_resources": await VideoResource.filter(created_by__in=source_ids).count(),
            "resource_folders": await ResourceFolder.filter(created_by__in=source_ids).count(),
            "creation_agent_conversations": await AgentConversation.filter(created_by__in=source_ids).count(),
            "chapter_exports": await ChapterExport.filter(created_by__in=source_ids).count(),
            "chapter_exports_collection_owner": await ChapterExport.filter(collection_owner__in=source_ids).count(),
            "remake_sources": await RemakeSource.filter(created_by__in=source_ids).count(),
            "remake_uploads": await RemakeUpload.filter(created_by__in=source_ids).count(),
            "editor_assets": await EditorAsset.filter(created_by__in=source_ids).count(),
            "team_invites": await TeamInvite.filter(created_by__in=source_ids).count(),
            "balance_transactions": await BalanceTransaction.filter(operator_user_id__in=source_ids).count(),
            "qiling_login_attempts": await QilingLoginAttempt.filter(binding_user_id__in=source_ids).count(),
            "user_sessions_to_delete": await UserSession.filter(user_id__in=source_ids).count(),
        },
    }
    return preview


async def migrate_accounts_to_target(
    source_ids: list[int],
    target_id: int,
    delete_sources: bool = True,
) -> dict[str, Any]:
    """Migrate all resources, memberships, and superadmin privileges from source users to target user in an atomic transaction."""
    preview = await get_consolidation_preview(source_ids, target_id)

    async with in_transaction():
        target = await User.filter(id=target_id).select_for_update().first()
        sources = await User.filter(id__in=source_ids).select_for_update().all()

        # 1. 转移超级管理员权限
        if any(s.is_super_admin for s in sources) and not target.is_super_admin:
            target.is_super_admin = True
            await target.save(update_fields=["is_super_admin", "updated_at"])

        # 2. 团队所有权转移
        await Team.filter(owner_user_id__in=source_ids).update(owner_user_id=target_id)

        # 3. 团队成员资格转移与去重合并
        for source_id in source_ids:
            source_members = await TeamMember.filter(user_id=source_id).all()
            for sm in source_members:
                existing_target_member = await TeamMember.filter(team_id=sm.team_id, user_id=target_id).first()
                if not existing_target_member:
                    sm.user_id = target_id
                    await sm.save(update_fields=["user_id", "updated_at"])
                else:
                    # 如果原先是管理员，确保目标用户在团队中也是管理员
                    if sm.role == "admin" and existing_target_member.role != "admin":
                        existing_target_member.role = "admin"
                        await existing_target_member.save(update_fields=["role", "updated_at"])
                    # 删除重复的旧成员记录
                    await sm.delete()

        # 4. 业务数据归属变更
        await Novel.filter(created_by__in=source_ids).update(created_by=target_id)
        await ModelUsageRecord.filter(user_id__in=source_ids).update(user_id=target_id)
        await AudioReference.filter(created_by__in=source_ids).update(created_by=target_id)
        await VideoResource.filter(created_by__in=source_ids).update(created_by=target_id)
        await ResourceFolder.filter(created_by__in=source_ids).update(created_by=target_id)
        await AgentConversation.filter(created_by__in=source_ids).update(created_by=target_id)
        await ChapterExport.filter(created_by__in=source_ids).update(created_by=target_id)
        await ChapterExport.filter(collection_owner__in=source_ids).update(collection_owner=target_id)
        await RemakeSource.filter(created_by__in=source_ids).update(created_by=target_id)
        await RemakeUpload.filter(created_by__in=source_ids).update(created_by=target_id)
        await EditorAsset.filter(created_by__in=source_ids).update(created_by=target_id)
        await TeamInvite.filter(created_by__in=source_ids).update(created_by=target_id)
        await BalanceTransaction.filter(operator_user_id__in=source_ids).update(operator_user_id=target_id)
        await QilingLoginAttempt.filter(binding_user_id__in=source_ids).update(binding_user_id=target_id)

        # 5. 会话清理（旧账号注销）
        await UserSession.filter(user_id__in=source_ids).delete()

        # 6. 删除或停用老账号
        if delete_sources:
            await User.filter(id__in=source_ids).delete()
            preview["sources_deleted"] = True
        else:
            await User.filter(id__in=source_ids).update(status=0, is_super_admin=False)
            preview["sources_deleted"] = False

    return preview
