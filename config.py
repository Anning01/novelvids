import os
from zoneinfo import ZoneInfo

import dotenv

dotenv.load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    DEPLOYMENT_ROLE = os.getenv("NOVELVIDS_ROLE", "studio").strip().lower()
    # 数据库配置
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite://./data/novelvids.db"  # 默认使用 SQLite 数据库
    )

    CREATION_AGENT_OPTIONAL_SKILLS_PATH: str = os.getenv("CREATION_AGENT_OPTIONAL_SKILLS_PATH", ".agents/skills")
    CREATION_AGENT_CHECKPOINT_PATH: str = os.getenv("CREATION_AGENT_CHECKPOINT_PATH", "data/creation_agent_checkpoints.db")

    # 应用配置
    APP_NAME: str = "猫影短剧"
    APP_DESC: str = "基于第三方AI模型的短剧/小说生成平台"
    VERSION: str = "1.0.0"
    DEBUG: bool = _env_bool("DEBUG", True)
    GENERATE_SCHEMAS: bool = _env_bool("GENERATE_SCHEMAS", True)

    # HTTP 安全配置：开发态保持兼容，生产环境通过环境变量收紧。
    API_DOCS_ENABLED: bool = _env_bool("API_DOCS_ENABLED", DEBUG)
    SECURITY_HEADERS_ENABLED: bool = _env_bool(
        "SECURITY_HEADERS_ENABLED", not DEBUG
    )
    EXPOSE_INTERNAL_ERRORS: bool = _env_bool("EXPOSE_INTERNAL_ERRORS", DEBUG)
    ALLOWED_HOSTS: list[str] = _env_list("ALLOWED_HOSTS", ["*"])
    ALLOWED_ORIGINS: list[str] = _env_list(
        "ALLOWED_ORIGINS", ["*"] if DEBUG else []
    )
    CORS_ALLOW_CREDENTIALS: bool = _env_bool("CORS_ALLOW_CREDENTIALS", False)
    CONTENT_SECURITY_POLICY: str = os.getenv(
        "CONTENT_SECURITY_POLICY",
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; form-action 'self'; "
        "img-src 'self' data: blob: https:; media-src 'self' blob: https:; "
        "font-src 'self' data: https:; style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com; "
        "connect-src 'self' https: wss:; worker-src 'self' blob:",
    )
    DOCS_CONTENT_SECURITY_POLICY: str = os.getenv(
        "DOCS_CONTENT_SECURITY_POLICY",
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'none'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    )

    # 仅信任由这些直连代理注入的客户端 IP 头，支持单 IP 或 CIDR。
    TRUSTED_PROXY_NETWORKS: list[str] = _env_list(
        "TRUSTED_PROXY_NETWORKS", ["127.0.0.1/32", "::1/128"]
    )

    # 登录限流：每 IP 的总尝试频率 + IP/用户名组合的失败窗口。
    LOGIN_RATE_LIMIT_ENABLED: bool = _env_bool("LOGIN_RATE_LIMIT_ENABLED", True)
    LOGIN_RATE_LIMIT_IP_ATTEMPTS: int = max(
        1, int(os.getenv("LOGIN_RATE_LIMIT_IP_ATTEMPTS", "30"))
    )
    LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS: int = max(
        1, int(os.getenv("LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS", "60"))
    )
    LOGIN_RATE_LIMIT_FAILURES: int = max(
        1, int(os.getenv("LOGIN_RATE_LIMIT_FAILURES", "5"))
    )
    LOGIN_RATE_LIMIT_FAILURE_WINDOW_SECONDS: int = max(
        1, int(os.getenv("LOGIN_RATE_LIMIT_FAILURE_WINDOW_SECONDS", "900"))
    )
    LOGIN_RATE_LIMIT_MAX_KEYS: int = max(
        100, int(os.getenv("LOGIN_RATE_LIMIT_MAX_KEYS", "10000"))
    )
    MEDIA_LIBRARY_SEED_ENABLED: bool = _env_bool(
        "MEDIA_LIBRARY_SEED_ENABLED", True
    )
    MODEL_CONFIG_SEED_ENABLED: bool = _env_bool(
        "MODEL_CONFIG_SEED_ENABLED", True
    )

    RESOURCE_LIBRARY_MAX_SIZE_MB = max(1, int(os.getenv("RESOURCE_LIBRARY_MAX_SIZE_MB", "200")))
    VIDEO_EDITOR_MAX_DURATION_SECONDS = max(1, int(os.getenv('VIDEO_EDITOR_MAX_DURATION_SECONDS', '7200')))
    VIDEO_EDITOR_RENDER_TIMEOUT = max(60, int(os.getenv('VIDEO_EDITOR_RENDER_TIMEOUT', '7200')))
    VIDEO_EDITOR_MAX_OVERLAYS = max(1, int(os.getenv('VIDEO_EDITOR_MAX_OVERLAYS', '32')))
    VIDEO_EDITOR_MAX_AUDIO_TRACKS = max(1, int(os.getenv('VIDEO_EDITOR_MAX_AUDIO_TRACKS', '32')))
    VIDEO_EDITOR_MAX_SOURCE_MB = max(1, int(os.getenv('VIDEO_EDITOR_MAX_SOURCE_MB', '2048')))

    # 微信支付 v3（Native 扫码支付）
    WECHAT_PAY_APP_ID: str = os.getenv("WECHAT_PAY_APP_ID", "").strip()
    WECHAT_PAY_MCH_ID: str = os.getenv("WECHAT_PAY_MCH_ID", "").strip()
    WECHAT_PAY_API_V3_KEY: str = os.getenv("WECHAT_PAY_API_V3_KEY", "").strip()
    WECHAT_PAY_SERIAL_NO: str = os.getenv("WECHAT_PAY_SERIAL_NO", "").strip()
    WECHAT_PAY_PRIVATE_KEY: str = os.getenv("WECHAT_PAY_PRIVATE_KEY", "").strip()
    WECHAT_PAY_PRIVATE_KEY_PATH: str = os.getenv("WECHAT_PAY_PRIVATE_KEY_PATH", "").strip()
    WECHAT_PAY_PUBLIC_KEY: str = os.getenv("WECHAT_PAY_PUBLIC_KEY", "").strip()
    WECHAT_PAY_PUBLIC_KEY_PATH: str = os.getenv("WECHAT_PAY_PUBLIC_KEY_PATH", "").strip()
    WECHAT_PAY_PUBLIC_KEY_ID: str = os.getenv("WECHAT_PAY_PUBLIC_KEY_ID", "").strip()
    WECHAT_PAY_NOTIFY_URL: str = os.getenv("WECHAT_PAY_NOTIFY_URL", "").strip()
    WECHAT_PAY_MOCK: bool = _env_bool("WECHAT_PAY_MOCK", False)

    # 媒体文件目录
    MEDIA_PATH = os.getenv("MEDIA_PATH", "./media")
    CHAPTER_EXPORT_PATH = os.getenv("CHAPTER_EXPORT_PATH", "./data/chapter-exports")

    # 时区配置
    TIMEZONE = "Asia/Shanghai"
    tz = ZoneInfo(TIMEZONE)
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # 自建工作台默认启用本地账号与团队。
    AUTH_ENABLED: bool = _env_bool("AUTH_ENABLED", DEPLOYMENT_ROLE == "studio")
    AUTH_PROVIDER: str = os.getenv("AUTH_PROVIDER", "password").strip().lower()
    if AUTH_PROVIDER not in {"password", "qiling"}:
        raise ValueError("AUTH_PROVIDER must be password or qiling")
    if DEPLOYMENT_ROLE == "studio":
        AUTH_PROVIDER = "password"
    QILING_API_BASE_URL: str = os.getenv(
        "QILING_API_BASE_URL", os.getenv("NOVELVIDS_DEV_QILING_API_BASE_URL", "")
    ).strip().rstrip("/")
    QILING_SIGNUP_ENABLED: bool = _env_bool("QILING_SIGNUP_ENABLED", False)
    if DEPLOYMENT_ROLE == "studio":
        QILING_API_BASE_URL = ""
        QILING_SIGNUP_ENABLED = False
    SUPER_ADMIN_USERNAME: str = os.getenv("SUPER_ADMIN_USERNAME", "")
    SUPER_ADMIN_PASSWORD: str = os.getenv("SUPER_ADMIN_PASSWORD", "")

    LEGAL_OPERATOR_NAME: str = os.getenv("LEGAL_OPERATOR_NAME", "").strip()
    LEGAL_CONTACT_EMAIL: str = os.getenv("LEGAL_CONTACT_EMAIL", "").strip()
    LEGAL_CONTACT_ADDRESS: str = os.getenv("LEGAL_CONTACT_ADDRESS", "").strip()
    LEGAL_EFFECTIVE_DATE: str = os.getenv("LEGAL_EFFECTIVE_DATE", "").strip()
    LEGAL_STORAGE_DESCRIPTION: str = os.getenv("LEGAL_STORAGE_DESCRIPTION", "").strip()
    LEGAL_RETENTION_DESCRIPTION: str = os.getenv("LEGAL_RETENTION_DESCRIPTION", "").strip()
    LEGAL_ACCOUNT_DELETION_DESCRIPTION: str = os.getenv("LEGAL_ACCOUNT_DELETION_DESCRIPTION", "").strip()
    LEGAL_AI_MARKING_DESCRIPTION: str = os.getenv("LEGAL_AI_MARKING_DESCRIPTION", "").strip()
    LEGAL_THIRD_PARTIES_JSON: str = os.getenv("LEGAL_THIRD_PARTIES_JSON", "").strip()

    # 会话有效期（小时）
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "168"))

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

    # Private temporary-object bucket on the platform; the local studio needs only its scoped API key.
    STUDIO_TEMP_BUCKET = os.getenv("STUDIO_TEMP_BUCKET", "")
    STUDIO_TEMP_REGION = os.getenv("STUDIO_TEMP_REGION", "")
    STUDIO_TEMP_TEAM_BYTES = int(os.getenv("STUDIO_TEMP_TEAM_BYTES", str(20 * 1024**3)))
    STUDIO_PLATFORM_BASE_URL = (
        os.getenv("STUDIO_PLATFORM_BASE_URL", "").strip() or "https://shortdramas.xiazq.com/v1"
    ).rstrip("/")
    STUDIO_PLATFORM_API_KEY = os.getenv("STUDIO_PLATFORM_API_KEY", "")
    STUDIO_MEDIA_CACHE_PATH = os.getenv("STUDIO_MEDIA_CACHE_PATH", "./data/studio-media")

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
    # 配置工作机地址时，重制工坊通过 SSH 处理媒体。
    REMAKE_MEDIA_SSH_HOST = os.getenv("REMAKE_MEDIA_SSH_HOST", "").strip()
    REMAKE_MEDIA_WORKER_PATH = os.getenv("REMAKE_MEDIA_WORKER_PATH", "/opt/novelvids-media-worker").strip()
    REMAKE_MEDIA_TIMEOUT_SECONDS = int(os.getenv("REMAKE_MEDIA_TIMEOUT_SECONDS", "3600"))
    REMAKE_MEDIA_MEMORY_MB = int(os.getenv("REMAKE_MEDIA_MEMORY_MB", "2048"))
    REMAKE_MEDIA_CPU_PERCENT = int(os.getenv("REMAKE_MEDIA_CPU_PERCENT", "100"))
    MEDIA_PROCESSING_REMOTE_ENABLED: bool = _env_bool("MEDIA_PROCESSING_REMOTE_ENABLED", False)
    MEDIA_PROCESSING_CONCURRENCY = max(1, int(os.getenv("MEDIA_PROCESSING_CONCURRENCY", "1")))


settings = Settings()
