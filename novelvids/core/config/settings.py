"""Core configuration module."""

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DB_",
        extra="ignore",
    )

    driver: str = Field(default="sqlite", description="Database driver: sqlite or postgres")
    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    user: str = Field(default="novelvids")
    password: str = Field(default="novelvids")
    name: str = Field(default="novelvids")
    sqlite_path: str = Field(default="./data/novelvids.db")

    def get_connection_url(self) -> str:
        """Get database connection URL based on driver."""
        if self.driver == "sqlite":
            return f"sqlite://{self.sqlite_path}"
        return f"postgres://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class RedisSettings(BaseSettings):
    """Redis configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="REDIS_",
        extra="ignore",
    )

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    db: int = Field(default=0)
    password: str | None = Field(default=None)

    def get_connection_url(self) -> str:
        """Get Redis connection URL."""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class ComfyUISettings(BaseSettings):
    """ComfyUI API configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="COMFYUI_",
        extra="ignore",
    )

    base_url: str = Field(default="http://localhost:8188")
    api_key: str | None = Field(default=None)
    timeout: int = Field(default=300, description="Request timeout in seconds")
    max_retries: int = Field(default=3)
    use_cloud: bool = Field(default=False, description="Use cloud ComfyUI API")
    cloud_base_url: str | None = Field(default=None)
    cloud_api_key: str | None = Field(default=None)


class StorageSettings(BaseSettings):
    """Storage configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="STORAGE_",
        extra="ignore",
    )

    base_path: str = Field(default="./data/storage")
    media_dir: str = Field(default="./media", description="Media files directory for static serving")
    max_file_size: int = Field(default=100 * 1024 * 1024, description="Max file size in bytes")


class BillingSettings(BaseSettings):
    """Billing configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BILLING_",
        extra="ignore",
    )

    enabled: bool = Field(default=True)
    cost_per_image: float = Field(default=0.01)
    cost_per_audio_second: float = Field(default=0.001)
    cost_per_video_second: float = Field(default=0.005)


class JWTSettings(BaseSettings):
    """JWT authentication settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="JWT_",
        extra="ignore",
    )

    secret_key: str = Field(default="your-secret-key-change-in-production")
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=30)
    refresh_token_expire_days: int = Field(default=7)


class LLMSettings(BaseSettings):
    """LLM API configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="LLM_",
        extra="ignore",
    )

    api_key: str = Field(default="")
    base_url: str = Field(default="https://api.openai.com/v1")
    model_name: str = Field(default="gpt-4o-mini")
    timeout: int = Field(default=60, description="Request timeout in seconds")


class ArkSettings(BaseSettings):
    """Volcengine Ark (Doubao) image generation settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ARK_",
        extra="ignore",
    )

    api_key: str = Field(default="")
    base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3")
    model_name: str = Field(default="doubao-seedream-4-5-251128")
    video_model: str = Field(default="doubao-seedance-1-0-lite-i2v-250428", description="Video generation model")
    image_size: str = Field(default="2K", description="Image size: 2K, 1080P, etc.")
    timeout: int = Field(default=120, description="Request timeout in seconds")


class ViduSettings(BaseSettings):
    """Vidu video generation settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VIDU_",
        extra="ignore",
    )

    api_key: str = Field(default="")
    base_url: str = Field(default="https://api.vidu.cn/ent/v2")
    model_name: str = Field(default="viduq2", description="Video generation model")
    timeout: int = Field(default=60, description="Request timeout in seconds")


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="NovelVids")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    api_prefix: str = Field(default="/api/v1")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    comfyui: ComfyUISettings = Field(default_factory=ComfyUISettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    billing: BillingSettings = Field(default_factory=BillingSettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ark: ArkSettings = Field(default_factory=ArkSettings)
    vidu: ViduSettings = Field(default_factory=ViduSettings)


def get_settings() -> Settings:
    """Get application settings singleton."""
    return Settings()


settings = get_settings()
