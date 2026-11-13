"""超级管理员引导：配置了引导账号且尚无超管时，应用启动自动创建。"""

import logging
from decimal import Decimal

from tortoise.transactions import in_transaction

from auth.models import Team, User
from auth.security import hash_password
from config import settings

logger = logging.getLogger(__name__)


async def ensure_super_admin() -> None:
    """AUTH_ENABLED=true 时调用：创建首个超管（若已存在则跳过）。"""
    if settings.AUTH_PROVIDER != "password":
        return
    studio = settings.DEPLOYMENT_ROLE == "studio"
    async with in_transaction() as db:
        if await User.filter(is_super_admin=True).using_db(db).exists():
            return
        first_studio = studio and not await User.all().using_db(db).exists() and not await Team.all().using_db(db).exists()
        username = settings.SUPER_ADMIN_USERNAME or ("admin" if first_studio else "")
        password = settings.SUPER_ADMIN_PASSWORD or ("123456" if first_studio else "")
        if not username or not password:
            logger.warning("请设置 SUPER_ADMIN_USERNAME 和 SUPER_ADMIN_PASSWORD 以创建超级管理员")
            return
        user, created = await User.get_or_create(username=username, defaults={
            "nickname": username, "password_hash": hash_password(password), "is_super_admin": True,
        }, using_db=db)
        if not created:
            return
        if first_studio:
            from services.team_provisioning import create_owned_team
            from services.balance import top_up

            team = await create_owned_team(user.id, name="默认团队")
            await top_up(team.id, Decimal("999999"), operator_user_id=user.id, note="工作台初始余额")
    logger.info("已创建超级管理员账号：%s", username)
