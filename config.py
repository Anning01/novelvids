import os
from zoneinfo import ZoneInfo

import dotenv

dotenv.load_dotenv()


class Settings:
    # 数据库配置
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite://./data/novelvids.db"  # 默认使用 SQLite 数据库
    )

    # 应用配置
    APP_NAME: str = "猫影短剧"
    APP_DESC: str = "基于第三方AI模型的短剧/小说生成平台"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    GENERATE_SCHEMAS: bool = os.getenv("GENERATE_SCHEMAS", "True").lower() == "true"

    # CORS配置
    ALLOWED_HOSTS: list = ["*"]
    ALLOWED_ORIGINS: list = ["*"]

    # 媒体文件目录
    MEDIA_PATH = os.getenv("MEDIA_PATH", "./media")

    # 时区配置
    TIMEZONE = "Asia/Shanghai"
    tz = ZoneInfo(TIMEZONE)
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # 登录与团队功能开关（默认关闭，与无鉴权版本行为一致）
    AUTH_ENABLED: bool = os.getenv("AUTH_ENABLED", "false").lower() == "true"

    # 会话有效期（小时）
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "168"))

    # 首个超级管理员引导账号（AUTH_ENABLED=true 且不存在超管时自动创建）
    SUPER_ADMIN_USERNAME: str = os.getenv("SUPER_ADMIN_USERNAME", "")
    SUPER_ADMIN_PASSWORD: str = os.getenv("SUPER_ADMIN_PASSWORD", "")


settings = Settings()
