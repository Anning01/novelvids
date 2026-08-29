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

    # ---- 对象存储（默认 local：本地磁盘，行为不变） ----
    OSS_PROVIDER: str = os.getenv("OSS_PROVIDER", "local")  # local | aliyun
    OSS_BUCKET: str = os.getenv("OSS_BUCKET", "")
    # 公网 endpoint（前端直传与公网访问域名拼接），如 oss-cn-beijing.aliyuncs.com
    OSS_ENDPOINT: str = os.getenv("OSS_ENDPOINT", "")
    # 内网 endpoint（服务端读写用，省流量），如 oss-cn-beijing-internal.aliyuncs.com
    OSS_INTERNAL_ENDPOINT: str = os.getenv("OSS_INTERNAL_ENDPOINT", "")
    # 公网访问前缀（可选 CDN/自定义域名），留空则用 https://{bucket}.{endpoint}
    OSS_PUBLIC_BASE: str = os.getenv("OSS_PUBLIC_BASE", "")
    OSS_ACCESS_KEY_ID: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    OSS_ACCESS_KEY_SECRET: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")

    # 视频供应商任务由后端持续收口，不依赖浏览器页面保持打开。
    VIDEO_RECONCILE_INTERVAL_SECONDS: int = max(
        5,
        int(os.getenv("VIDEO_RECONCILE_INTERVAL_SECONDS", "30")),
    )
    VIDEO_RECONCILE_BATCH_SIZE: int = max(
        1,
        int(os.getenv("VIDEO_RECONCILE_BATCH_SIZE", "50")),
    )
    REMAKE_ANALYSIS_CONCURRENCY: int = max(
        1,
        int(os.getenv("REMAKE_ANALYSIS_CONCURRENCY", "2")),
    )


settings = Settings()
