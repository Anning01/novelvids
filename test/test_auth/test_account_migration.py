from datetime import datetime, timedelta, timezone
import pytest
from auth.models import QilingIdentity, Team, TeamMember, User, UserSession
from config import settings
from models.novel import Novel
from services.account_migration import get_consolidation_preview, migrate_accounts_to_target

pytestmark = [pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def configured_issuer(monkeypatch):
    monkeypatch.setattr(settings, "QILING_API_BASE_URL", "https://identity.example.test")



async def test_account_migration_full_flow():
    # 1. 创建源用户 admin (superadmin)
    admin = await User.create(username="test_admin_src", nickname="超管源", is_super_admin=True, status=1)

    # 2. 创建源用户 testuser (拥有团队与小说)
    testuser = await User.create(username="test_user_src", nickname="测试源", is_super_admin=False, status=1)
    team = await Team.create(name="迁移测试团队", owner_user_id=testuser.id, balance="100.000000", status=1)
    await TeamMember.create(team_id=team.id, user_id=testuser.id, role="admin", status=1)
    novel = await Novel.create(name="迁移测试小说", team_id=team.id, created_by=testuser.id)
    await UserSession.create(
        user_id=testuser.id,
        token_hash="hash_test_user_src",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    # 3. 创建目标用户 qiling user (安宁)
    target = await User.create(username="qiling_target", nickname="安宁目标", is_super_admin=False, status=1)
    await QilingIdentity.create(user=target, issuer=settings.QILING_API_BASE_URL, subject="verified-target")
    target_team = await Team.create(name="安宁个人团队", owner_user_id=target.id, balance="0", status=1)
    await TeamMember.create(team_id=target_team.id, user_id=target.id, role="admin", status=1)

    # 4. 预览检查
    preview = await get_consolidation_preview([admin.id, testuser.id], target.id)
    assert preview["target_will_become_super_admin"] is True
    assert preview["records_to_migrate"]["teams_owned"] == 1
    assert preview["records_to_migrate"]["novels"] == 1
    assert preview["records_to_migrate"]["user_sessions_to_delete"] == 1

    # 5. 执行迁移并删除源账号
    result = await migrate_accounts_to_target([admin.id, testuser.id], target.id, delete_sources=True)
    assert result["sources_deleted"] is True

    # 6. 验证目标账号
    updated_target = await User.get(id=target.id)
    assert updated_target.is_super_admin is True

    # 验证团队所有权转移
    updated_team = await Team.get(id=team.id)
    assert updated_team.owner_user_id == target.id

    # 验证团队成员
    target_member = await TeamMember.filter(team_id=team.id, user_id=target.id).first()
    assert target_member is not None
    assert target_member.role == "admin"

    # 验证小说归属转移
    updated_novel = await Novel.get(id=novel.id)
    assert updated_novel.created_by == target.id

    # 验证源用户被删除
    assert await User.filter(id__in=[admin.id, testuser.id]).count() == 0
    assert await UserSession.filter(user_id__in=[admin.id, testuser.id]).count() == 0


async def accounts():
    source = await User.create(username="migration-source", is_super_admin=True)
    target = await User.create(username="migration-target")
    await QilingIdentity.create(user=target, issuer=settings.QILING_API_BASE_URL, subject="target")
    return source, target


async def test_merge_preserves_balances_spend_limits_strongest_role_and_existing_target_session():
    source, target = await accounts()
    team = await Team.create(name="merge-shared", owner_user_id=source.id, balance="752.462167")
    await TeamMember.create(user=source, team=team, role="creator", total_cost="195.832141", cost_limit="250")
    await TeamMember.create(user=target, team=team, role="viewer", total_cost="4", cost_limit="10", status=0)
    session = await UserSession.create(user=target, token_hash="keep-target-session", expires_at=datetime.now(timezone.utc)+timedelta(days=1))
    await migrate_accounts_to_target([source.id],target.id)
    merged = await TeamMember.get(user=target, team=team)
    assert str(merged.total_cost) == "199.832141"
    assert merged.cost_limit == 260
    assert merged.role == "creator" and merged.status == 1
    await team.refresh_from_db()
    assert str(team.balance) == "752.462167" and team.owner_user_id == target.id
    assert await UserSession.filter(id=session.id).exists()


async def test_orders_export_lease_tasks_and_retry_receipts_survive_source_deletion():
    from uuid import uuid4
    from auth.models import RechargeOrder, QilingLoginAttempt
    from models.ai_task import AiTask
    from models.agent_submission import AgentSubmission
    from models.chapter_export import ChapterExport
    from services.creation_agent.submissions import submission_key
    from utils.enums import TaskStatusEnum
    source,target=await accounts()
    team=await Team.create(name="preserve-history",balance="100")
    project=await Novel.create(name="preserve-history",created_by=source.id,team_id=team.id)
    order=await RechargeOrder.create(out_trade_no="MIGRATION_ORDER",team=team,user_id=source.id,amount="50",status="paid")
    lease=uuid4()
    export=await ChapterExport.create(novel_id=project.id,chapter_id=1,created_by=source.id,
        identity_key="migration-export",source_version="version",collection_owner=lease)
    params={"user_id":source.id,"team_id":team.id,"submission_id":"client-request","submission_hash":"hash"}
    task=await AiTask.create(task_type=4,status=TaskStatusEnum.completed.value,request_params=params)
    receipt=await AgentSubmission.create(key=submission_key(params),request_hash="hash",task_type=4,task=task)
    await QilingLoginAttempt.create(token_hash="source-pending-binding",upstream_state="state",issuer=settings.QILING_API_BASE_URL,binding_user=source,expires_at=datetime.now(timezone.utc)+timedelta(minutes=5))
    await migrate_accounts_to_target([source.id],target.id)
    await export.refresh_from_db();await order.refresh_from_db();await task.refresh_from_db();await receipt.refresh_from_db()
    assert export.created_by==target.id and export.collection_owner==lease
    assert order.user_id==target.id and order.status=="paid" and order.amount==50
    assert task.request_params=={**params,"user_id":target.id}
    assert receipt.key==submission_key(task.request_params)
    assert not await QilingLoginAttempt.filter(token_hash="source-pending-binding").exists()
    assert await QilingIdentity.filter(user=target,subject="target").exists()


@pytest.mark.parametrize("state", [1, 2, 6])
async def test_active_tasks_abort_the_entire_migration(state):
    from models.ai_task import AiTask
    source,target=await accounts()
    team=await Team.create(name="running-task-team",owner_user_id=source.id,balance="100")
    await TeamMember.create(team=team,user=source,role="admin",total_cost="7")
    await AiTask.create(task_type=4,status=state,request_params={"user_id":source.id})
    with pytest.raises(ValueError,match="active tasks"):
        await migrate_accounts_to_target([source.id],target.id)
    await team.refresh_from_db();await target.refresh_from_db()
    assert team.owner_user_id==source.id and team.balance==100
    assert await TeamMember.filter(team=team,user=source,total_cost=7).exists()
    assert await User.filter(id=source.id).exists()
    assert target.is_super_admin is False


async def test_unverified_or_wrong_issuer_target_is_rejected():
    source,target=await accounts()
    await QilingIdentity.filter(user=target).update(issuer="https://other.example.test")
    with pytest.raises(ValueError,match="verified identity"):
        await migrate_accounts_to_target([source.id],target.id)
    assert await User.filter(id=source.id).exists()


async def test_ambiguous_nickname_cannot_select_a_deletion_target():
    from scripts.migrate_accounts_to_qiling import resolve_user_id
    await User.create(username="ambiguous-one",nickname="same")
    await User.create(username="ambiguous-two",nickname="same")
    with pytest.raises(ValueError,match="ambiguous"):
        await resolve_user_id("same")


async def test_conflicting_task_receipts_roll_back_every_account_change():
    from models.ai_task import AiTask
    from models.agent_submission import AgentSubmission
    from services.creation_agent.submissions import submission_key
    source,target=await accounts()
    receipts=[]
    for user in (source,target):
        params={"user_id":user.id,"team_id":1,"submission_id":"same-request","submission_hash":"hash"}
        task=await AiTask.create(task_type=4,status=3,request_params=params)
        receipts.append(await AgentSubmission.create(key=submission_key(params),request_hash="hash",task_type=4,task=task))
    original=receipts[0].key
    with pytest.raises(ValueError,match="Conflicting task retry"):
        await migrate_accounts_to_target([source.id],target.id)
    await receipts[0].refresh_from_db();await target.refresh_from_db()
    assert receipts[0].key==original and not target.is_super_admin
    assert await User.filter(id=source.id).exists()


async def test_clip_retry_identity_moves_without_recreating_the_project():
    import json
    from uuid import NAMESPACE_URL,uuid4,uuid5
    source,target=await accounts()
    request_id=str(uuid4())
    project=await Novel.create(name="clip-history",author="片段创作",created_by=source.id,
        creation_idempotency_key="clip:"+str(uuid5(NAMESPACE_URL,f"None:{source.id}:{request_id}")),
        project_setting=json.dumps({"request_id":request_id}))
    await migrate_accounts_to_target([source.id],target.id)
    await project.refresh_from_db()
    assert project.created_by==target.id
    assert project.creation_idempotency_key=="clip:"+str(uuid5(NAMESPACE_URL,f"None:{target.id}:{request_id}"))
    assert await Novel.all().count()==1
