"""超级管理员引导：配置了引导账号且尚无超管时，应用启动自动创建。"""

import logging

from auth.models import User
from auth.security import hash_password
from config import settings

logger = logging.getLogger(__name__)


async def ensure_super_admin() -> None:
    """AUTH_ENABLED=true 时调用：创建首个超管（若已存在则跳过）。"""
    if not settings.SUPER_ADMIN_USERNAME or not settings.SUPER_ADMIN_PASSWORD:
        logger.warning(
            "AUTH_ENABLED=true 但未配置 SUPER_ADMIN_USERNAME / "
            "SUPER_ADMIN_PASSWORD，无法自动创建超级管理员"
        )
        return
    if await User.filter(is_super_admin=True).exists():
        return
    if await User.filter(username=settings.SUPER_ADMIN_USERNAME).exists():
        logger.warning(
            "用户名 %s 已被普通用户占用，跳过超管自动创建",
            settings.SUPER_ADMIN_USERNAME,
        )
        return
    await User.create(
        username=settings.SUPER_ADMIN_USERNAME,
        nickname=settings.SUPER_ADMIN_USERNAME,
        password_hash=hash_password(settings.SUPER_ADMIN_PASSWORD),
        is_super_admin=True,
    )
    logger.info("已创建超级管理员账号：%s", settings.SUPER_ADMIN_USERNAME)
