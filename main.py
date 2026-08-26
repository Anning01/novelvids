from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from tortoise import Tortoise
from tortoise.exceptions import (
    DoesNotExist,
    IntegrityError,
    ValidationError as TortoiseValidationError,
)

from api import api_router
from config import settings
from exceptions.handlers import (
    http_exception_handler,
    global_exception_handler,
    validation_exception_handler,
    database_exception_handler,
)
from services.ai_task_executor import ai_task_executor
from services.extraction.handler import ExtractionTaskHandler
from services.reference.handler import AssetReferenceHandler
from services.project_analysis.handler import ProjectAnalysisTaskHandler
from services.storyboard.handler import StoryboardTaskHandler
from utils.enums import AiTaskTypeEnum
from services.media_library_seed import ensure_media_library_seed_data
from services.model_config_seed import ensure_model_config_seed_data
from services.video.reconciler import VideoTaskReconciler
from services.video.last_frame_backfill import backfill_last_frame_continuity
from controllers.video import video_controller
from services.schema_compat import (
    ensure_ai_model_config_schema,
    ensure_novel_analysis_schema,
    ensure_shared_team_columns,
    ensure_usage_record_schema,
)

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    await Tortoise.init(config=tortoise_config)
    if settings.GENERATE_SCHEMAS:
        await Tortoise.generate_schemas(safe=True)
    await ensure_ai_model_config_schema()
    await ensure_novel_analysis_schema()
    await ensure_usage_record_schema()
    # 共享表团队增量列：无条件补齐（旧库在关闭开关时同样需要，纯增量幂等）
    await ensure_shared_team_columns()
    await backfill_last_frame_continuity()
    await ensure_media_library_seed_data()
    await ensure_model_config_seed_data()
    if settings.AUTH_ENABLED:
        from auth.bootstrap import ensure_super_admin
        from services.schema_compat import ensure_team_schema

        await ensure_team_schema()
        await ensure_super_admin()
    # 清理上次进程遗留的 pending/running 任务（BackgroundTask 不跨重启存活）
    await ai_task_executor.fail_stale_on_boot()
    await video_task_reconciler.start()
    try:
        yield
    finally:
        await video_task_reconciler.stop()
        await Tortoise.close_connections()


app = FastAPI(title=settings.APP_NAME, version=settings.VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册异常处理器
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(DoesNotExist, database_exception_handler)
app.add_exception_handler(IntegrityError, database_exception_handler)
app.add_exception_handler(TortoiseValidationError, database_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)


app.include_router(api_router, prefix="/api")

# 状态探测路由在两种模式下都注册，前端据此渲染登录 UI 或保持无鉴权体验
from auth.api import public_router as auth_public_router

app.include_router(auth_public_router, prefix="/api/auth", tags=["认证与会话"])

# AUTH_ENABLED=true 时注册鉴权路由；关闭时不存在任何登录接口
if settings.AUTH_ENABLED:
    from auth.api import router as auth_router
    from api.team import router as team_router
    from api.user import router as user_router

    app.include_router(auth_router, prefix="/api/auth", tags=["认证与会话"])
    app.include_router(team_router, prefix="/api/team", tags=["团队与余额"])
    app.include_router(user_router, prefix="/api/users", tags=["用户管理"])

# 注册 AI 任务处理器
ai_task_executor.register(AiTaskTypeEnum.extraction, ExtractionTaskHandler())
ai_task_executor.register(AiTaskTypeEnum.reference_image, AssetReferenceHandler())
ai_task_executor.register(AiTaskTypeEnum.storyboard, StoryboardTaskHandler())
ai_task_executor.register(AiTaskTypeEnum.project_analysis, ProjectAnalysisTaskHandler())


# 为媒体（图像、视频、音频）安装静态文件
media_path = Path(settings.MEDIA_PATH)
media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# 确保SQLite数据库存在数据目录
data_path = Path("./data")
data_path.mkdir(parents=True, exist_ok=True)
