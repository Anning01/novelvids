from pathlib import Path
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import register_tortoise
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
from services.storyboard.handler import StoryboardTaskHandler
from utils.enums import AiTaskTypeEnum

app = FastAPI(title=settings.APP_NAME, version=settings.VERSION)

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

# 注册 AI 任务处理器
ai_task_executor.register(AiTaskTypeEnum.extraction, ExtractionTaskHandler())
ai_task_executor.register(AiTaskTypeEnum.reference_image, AssetReferenceHandler())
ai_task_executor.register(AiTaskTypeEnum.storyboard, StoryboardTaskHandler())


# 定义包含时区的配置字典
tortoise_config = {
    "connections": {"default": settings.DATABASE_URL},
    "apps": {
        "models": {
            "models": [f"models.{module}" for module in __import__("models").__all__],
            "default_connection": "default",
        }
    },
    "use_tz": True,  # 启用时区支持
    "timezone": settings.TIMEZONE,  # 设置为北京时间（+8时区）
}


# 为媒体（图像、视频、音频）安装静态文件
media_path = Path(settings.MEDIA_PATH)
media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# 确保SQLite数据库存在数据目录
data_path = Path("./data")
data_path.mkdir(parents=True, exist_ok=True)

register_tortoise(
    app,
    config=tortoise_config,  # 传递包含时区的配置
    generate_schemas=settings.GENERATE_SCHEMAS,
    add_exception_handlers=True,
)
