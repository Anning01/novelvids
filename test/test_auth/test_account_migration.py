from datetime import datetime, timedelta, timezone
import pytest
from auth.models import Team, TeamMember, User, UserSession
from models.novel import Novel
from services.account_migration import get_consolidation_preview, migrate_accounts_to_target

pytestmark = [pytest.mark.asyncio]


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
