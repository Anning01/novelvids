"""Atomically consolidate explicitly selected accounts into a verified Qiling user."""

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from tortoise.transactions import in_transaction

from auth.models import BalanceTransaction, QilingIdentity, QilingLoginAttempt, RechargeOrder, Team, TeamInvite, TeamMember, User, UserSession
from config import settings
from models.ai_task import AiTask
from models.agent_submission import AgentSubmission
from models.audio_reference import AudioReference
from models.chapter_export import ChapterExport
from models.creation_agent import AgentConversation
from models.video_edit import EditorAsset
from models.novel import Novel
from models.remake_source import RemakeSource
from models.remake_upload import RemakeUpload
from models.resource_library import ResourceFolder, VideoResource
from models.usage_record import ModelUsageRecord
from services.creation_agent.submissions import submission_key
from utils.enums import TaskStatusEnum


# collection_owner is a UUID collection lease, never a user ID.
OWNER_FIELDS = (
    ("novels", Novel, "created_by"),
    ("model_usage_records", ModelUsageRecord, "user_id"),
    ("audio_references", AudioReference, "created_by"),
    ("video_resources", VideoResource, "created_by"),
    ("resource_folders", ResourceFolder, "created_by"),
    ("creation_agent_conversations", AgentConversation, "created_by"),
    ("chapter_exports", ChapterExport, "created_by"),
    ("remake_sources", RemakeSource, "created_by"),
    ("remake_uploads", RemakeUpload, "created_by"),
    ("editor_assets", EditorAsset, "created_by"),
    ("team_invites", TeamInvite, "created_by"),
    ("balance_transactions", BalanceTransaction, "operator_user_id"),
    ("recharge_orders", RechargeOrder, "user_id"),
)
ROLE_RANK = {"viewer": 0, "creator": 1, "admin": 2}


async def get_consolidation_preview(source_ids: list[int], target_id: int) -> dict[str, Any]:
    if not source_ids or len(source_ids) != len(set(source_ids)) or target_id in source_ids:
        raise ValueError("Specify distinct source accounts and a separate target")
    target = await User.get_or_none(id=target_id, status=1)
    if target is None:
        raise ValueError("An active receiving account is required")
    if not await QilingIdentity.filter(user_id=target_id, issuer=settings.QILING_API_BASE_URL).exclude(issuer="").exists():
        raise ValueError("The target must have a verified identity for the configured Qiling issuer")
    sources = await User.filter(id__in=source_ids)
    if {user.id for user in sources} != set(source_ids):
        raise ValueError("One or more source accounts do not exist")
    counts = {name: await model.filter(**{field + "__in": source_ids}).count()
              for name, model, field in OWNER_FIELDS}
    counts.update({
        "teams_owned": await Team.filter(owner_user_id__in=source_ids).count(),
        "team_members": await TeamMember.filter(user_id__in=source_ids).count(),
        "qiling_login_attempts_to_delete": await QilingLoginAttempt.filter(binding_user_id__in=source_ids).count(),
        "user_sessions_to_delete": await UserSession.filter(user_id__in=source_ids).count(),
    })
    return {
        "target_id": target_id,
        "source_ids": source_ids,
        "target_is_super_admin_before": target.is_super_admin,
        "target_will_become_super_admin": target.is_super_admin or any(user.is_super_admin for user in sources),
        "records_to_migrate": counts,
    }


async def _merge_memberships(source_ids: list[int], target_id: int) -> None:
    for member in await TeamMember.filter(user_id__in=source_ids).order_by("id").select_for_update():
        existing = await TeamMember.filter(team_id=member.team_id, user_id=target_id).select_for_update().first()
        if existing is None:
            member.user_id = target_id
            await member.save(update_fields=["user_id", "updated_at"])
            continue
        existing.role = max((existing.role, member.role), key=ROLE_RANK.__getitem__)
        existing.status = max(existing.status, member.status)
        existing.total_cost += member.total_cost
        existing.cost_limit = (None if existing.cost_limit is None or member.cost_limit is None
                               else existing.cost_limit + member.cost_limit)
        await existing.save(update_fields=["role", "status", "total_cost", "cost_limit", "updated_at"])
        await member.delete()


async def _transfer_task_owners(source_ids: list[int], target_id: int) -> None:
    for task in await AiTask.all().select_for_update():
        params = task.request_params or {}
        if params.get("user_id") not in source_ids:
            continue
        if task.status in {TaskStatusEnum.pending.value, TaskStatusEnum.running.value, TaskStatusEnum.queued.value}:
            raise ValueError("Source accounts have active tasks; wait for them to finish before migration")
        updated = {**params, "user_id": target_id}
        key = submission_key(updated)
        if key:
            for receipt in await AgentSubmission.filter(task_id=task.id).select_for_update():
                if await AgentSubmission.filter(key=key).exclude(id=receipt.id).exists():
                    raise ValueError("Conflicting task retry receipts require review before migration")
                receipt.key = key
                await receipt.save(update_fields=["key", "updated_at"])
        task.request_params = updated
        await task.save(update_fields=["request_params", "updated_at"])


async def _transfer_clip_retry_keys(source_ids: list[int], target_id: int) -> None:
    import json
    for project in await Novel.filter(created_by__in=source_ids, author="片段创作"):
        context = json.loads(project.project_setting or "{}")
        request_id = context.get("request_id")
        if not request_id or not (project.creation_idempotency_key or "").startswith("clip:"):
            continue
        key = "clip:" + str(uuid5(NAMESPACE_URL, f"{project.team_id}:{target_id}:{request_id}"))
        if await Novel.filter(creation_idempotency_key=key).exclude(id=project.id).exists():
            raise ValueError("Conflicting clip retry keys require review before migration")
        project.creation_idempotency_key = key
        await project.save(update_fields=["creation_idempotency_key", "updated_at"])


async def migrate_accounts_to_target(source_ids: list[int], target_id: int, delete_sources: bool = True) -> dict[str, Any]:
    async with in_transaction():
        # Lock in stable order and revalidate inside the transaction before changing ownership.
        await User.filter(id__in=[*source_ids, target_id]).order_by("id").select_for_update()
        preview = await get_consolidation_preview(source_ids, target_id)
        target = await User.get(id=target_id)
        target.is_super_admin = preview["target_will_become_super_admin"]
        await target.save(update_fields=["is_super_admin", "updated_at"])
        await Team.filter(owner_user_id__in=source_ids).update(owner_user_id=target_id)
        await _merge_memberships(source_ids, target_id)
        await _transfer_task_owners(source_ids, target_id)
        await _transfer_clip_retry_keys(source_ids, target_id)
        for _, model, field in OWNER_FIELDS:
            await model.filter(**{field + "__in": source_ids}).update(**{field: target_id})
        # Pending bindings must not be reassigned to a different account.
        await QilingLoginAttempt.filter(binding_user_id__in=source_ids).delete()
        await UserSession.filter(user_id__in=source_ids).delete()
        if delete_sources:
            await User.filter(id__in=source_ids).delete()
        else:
            await User.filter(id__in=source_ids).update(status=0, is_super_admin=False)
        preview["sources_deleted"] = delete_sources
    return preview
