from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from tortoise import Tortoise
from tortoise.exceptions import (
    DoesNotExist,
    IntegrityError,
    ValidationError as TortoiseValidationError,
)

from config import settings
from exceptions.handlers import (
    http_exception_handler,
    global_exception_handler,
    validation_exception_handler,
    database_exception_handler,
)
from exceptions.remake import RemakeError, remake_exception_handler
from services.ai_task_executor import ai_task_executor
from services.media_types import register_media_mime_types
from services.extraction.handler import ExtractionTaskHandler
from services.reference.handler import AssetReferenceHandler
from services.project_analysis.handler import ProjectAnalysisTaskHandler
from services.storyboard.handler import StoryboardTaskHandler
from services.creation_agent.handler import CreationAgentTaskHandler
from services.remake.handler import RemakeDecompositionTaskHandler
from services.remake.uploads import remake_upload_service
from utils.enums import AiTaskTypeEnum
from services.media_library_seed import ensure_media_library_seed_data
from services.model_config_seed import ensure_model_config_seed_data
from services.video.reconciler import VideoTaskReconciler
from services.video.last_frame_backfill import backfill_last_frame_continuity
from controllers.video import video_controller
from services.schema_compat import (
    ensure_creation_agent_schema,
    ensure_ai_model_config_schema,
    ensure_novel_analysis_schema,
    ensure_remake_schema,
    ensure_shared_team_columns,
    ensure_usage_record_schema,
    ensure_voice_reference_schema,
)
from services.security.headers import SecurityHeadersMiddleware

# 定义包含时区的配置字典
# AUTH_ENABLED=true 时注册鉴权与团队相关模型；关闭时与无鉴权版本完全一致
_model_modules = [f"models.{module}" for module in __import__("models").__all__]
if settings.AUTH_ENABLED:
    _model_modules.append("auth.models")

tortoise_config = {
    "connections": {"default": settings.DATABASE_URL},
    "apps": {
        "models": {
            "models": _model_modules,
            "default_connection": "default",
        }
    },
    "use_tz": True,
    "timezone": settings.TIMEZONE,
}

video_task_reconciler = VideoTaskReconciler(
    video_controller.query_status,
    interval_seconds=settings.VIDEO_RECONCILE_INTERVAL_SECONDS,
    batch_size=settings.VIDEO_RECONCILE_BATCH_SIZE,
)


async def _initialize_database_schema() -> None:
    """Initialize storage while keeping legacy PostgreSQL installs bootable."""
    await Tortoise.init(config=tortoise_config)
    # PostgreSQL emits column comments for existing tables during safe schema
    # generation. Add fields referenced by the current models first, otherwise
    # startup fails before the compatibility migrations can run.
    include_compat_indexes = not settings.GENERATE_SCHEMAS
    await ensure_remake_schema(include_indexes=include_compat_indexes)
    await ensure_voice_reference_schema(include_indexes=include_compat_indexes)
    await ensure_creation_agent_schema()
    from services.schema_compat import ensure_resource_library_schema
    await ensure_resource_library_schema()
    # Ownership columns must exist before generating the scoped project-name index.
    await ensure_shared_team_columns()
    from services.schema_compat import ensure_chapter_screenplay_schema
    await ensure_chapter_screenplay_schema()
    await ensure_novel_analysis_schema()
    if settings.AUTH_ENABLED:
        from services.schema_compat import _ensure_qiling_issuer_columns, ensure_recharge_refund_columns
        await _ensure_qiling_issuer_columns(Tortoise.get_connection("default"))
        await ensure_recharge_refund_columns()
    if settings.GENERATE_SCHEMAS:
        await Tortoise.generate_schemas(safe=True)
    await ensure_ai_model_config_schema()
    await ensure_usage_record_schema()
    from services.schema_compat import ensure_agent_operation_schema
    await ensure_agent_operation_schema()
    from services.schema_compat import ensure_video_editor_schema
    await ensure_video_editor_schema()
    from services.schema_compat import ensure_recharge_order_schema
    await ensure_recharge_order_schema()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await _initialize_database_schema()
    if settings.DEPLOYMENT_ROLE == "studio":
        await remake_upload_service.cleanup_expired()
        await backfill_last_frame_continuity()
        if settings.MEDIA_LIBRARY_SEED_ENABLED:
            await ensure_media_library_seed_data()
    if settings.MODEL_CONFIG_SEED_ENABLED:
        await ensure_model_config_seed_data()
    if settings.AUTH_ENABLED:
        from services.schema_compat import ensure_team_schema

        await ensure_team_schema()
        if settings.AUTH_PROVIDER == "password":
            from auth.bootstrap import ensure_super_admin
            await ensure_super_admin()
    if settings.DEPLOYMENT_ROLE == "platform":
        import asyncio
        from services.platform.temporary_media import expire_periodically
        from services.platform.videos import reconcile_videos
        from services.platform.calls import recover_measured
        from services.platform.chat import settle_periodically, stop_streams
        await recover_measured()
        reconciler = asyncio.create_task(settle_periodically())
        expiry = asyncio.create_task(expire_periodically())
        videos = asyncio.create_task(reconcile_videos())
        try:
            yield
        finally:
            reconciler.cancel()
            expiry.cancel()
            videos.cancel()
            await asyncio.gather(reconciler, expiry, videos, return_exceptions=True)
            await stop_streams()
            await Tortoise.close_connections()
        return
    # 清理上次进程遗留的 pending/running 任务（BackgroundTask 不跨重启存活）
    await ai_task_executor.fail_stale_on_boot()
    await video_task_reconciler.start()
    from services.creation_agent.recovery import production_recovery
    await production_recovery.start()
    from services.video_editor.exports import editor_export_worker
    await editor_export_worker.start()
    try:
        yield
    finally:
        await editor_export_worker.stop()
        await production_recovery.stop()
        await video_task_reconciler.stop()
        await Tortoise.close_connections()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.API_DOCS_ENABLED else None,
)

from services.locale_middleware import LocaleMiddleware

app.add_middleware(LocaleMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
if settings.ALLOWED_HOSTS and "*" not in settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
if settings.SECURITY_HEADERS_ENABLED:
    app.add_middleware(
        SecurityHeadersMiddleware,
        content_security_policy=settings.CONTENT_SECURITY_POLICY,
        docs_content_security_policy=settings.DOCS_CONTENT_SECURITY_POLICY,
    )

# 注册异常处理器
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(DoesNotExist, database_exception_handler)
app.add_exception_handler(IntegrityError, database_exception_handler)
app.add_exception_handler(TortoiseValidationError, database_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(RemakeError, remake_exception_handler)


if settings.DEPLOYMENT_ROLE == "platform":
    if not settings.AUTH_ENABLED:
        raise RuntimeError("Platform deployment requires AUTH_ENABLED=true")
    from api.platform import console_router, developer_router
    app.include_router(console_router, prefix="/api")
    developer_api = FastAPI(title="猫影模型 API", version="1", docs_url=None, redoc_url=None)
    developer_api.include_router(developer_router)
    app.mount("/v1", developer_api)
elif settings.DEPLOYMENT_ROLE == "studio":
    from api import api_router
    app.include_router(api_router, prefix="/api")
else:
    raise RuntimeError("NOVELVIDS_ROLE must be studio or platform")

# 状态探测路由在两种模式下都注册，前端据此渲染登录 UI 或保持无鉴权体验
from auth.api import public_router as auth_public_router

app.include_router(auth_public_router, prefix="/api/auth", tags=["认证与会话"])

# AUTH_ENABLED=true 时注册鉴权路由；关闭时不存在任何登录接口
if settings.AUTH_ENABLED:
    from auth.api import router as auth_router
    from api.team import router as team_router
    from api.user import router as user_router
    from controllers.team import team_controller
    from starlette.requests import Request

    app.include_router(auth_router, prefix="/api/auth", tags=["认证与会话"])
    app.include_router(team_router, prefix="/api/team", tags=["团队与余额"])
    app.include_router(user_router, prefix="/api/users", tags=["用户管理"])

    @app.post("/api/payment/wechat/notify", tags=["微信支付通知"])
    async def global_wechat_pay_notify(request: Request):
        return await team_controller.handle_wechat_notify(
            await request.body(), headers=request.headers
        )

# 注册 AI 任务处理器
ai_task_executor.register(AiTaskTypeEnum.extraction, ExtractionTaskHandler())
ai_task_executor.register(AiTaskTypeEnum.reference_image, AssetReferenceHandler())
ai_task_executor.register(AiTaskTypeEnum.storyboard, StoryboardTaskHandler())
from services.video_enhancement.handler import EnhanceExportHandler
ai_task_executor.register(AiTaskTypeEnum.video_enhancement, EnhanceExportHandler())
ai_task_executor.register(AiTaskTypeEnum.creation_agent, CreationAgentTaskHandler())
ai_task_executor.register(AiTaskTypeEnum.project_analysis, ProjectAnalysisTaskHandler())
from services.chapter_screenplay import ScreenplayHandler
ai_task_executor.register(AiTaskTypeEnum.screenplay, ScreenplayHandler())
from services.storyboard.prompt_optimization import PromptOptimizationHandler
ai_task_executor.register(AiTaskTypeEnum.prompt_optimization, PromptOptimizationHandler())
ai_task_executor.register(
    AiTaskTypeEnum.remake_decomposition,
    RemakeDecompositionTaskHandler(),
)


# 为媒体（图像、视频、音频）安装静态文件
register_media_mime_types()
media_path = Path(settings.MEDIA_PATH)
media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# 确保SQLite数据库存在数据目录
data_path = Path("./data")
data_path.mkdir(parents=True, exist_ok=True)
