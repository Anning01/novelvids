"""FastAPI application factory."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from tortoise.contrib.fastapi import register_tortoise

from novelvids.api.middleware import CORSMiddleware as CORSConfig
from novelvids.api.middleware import LoggingMiddleware
from novelvids.api.v1 import router as v1_router
from novelvids.core.config import settings
from novelvids.infrastructure.database.config import get_tortoise_config


# 配置标准 logging 转发到 loguru
class InterceptHandler(logging.Handler):
    """拦截标准 logging 并转发到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        # 获取对应的 loguru 级别
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找到调用者
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging():
    """配置日志系统。"""
    # 移除默认的 loguru handler
    logger.remove()

    # 添加控制台输出，带颜色
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG",
        colorize=True,
    )

    # 拦截标准 logging
    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG, force=True)

    # 设置我们关心的模块的日志级别
    for logger_name in [
        "novelvids.application.services.storyboard_task_service",
        "novelvids.domain.services.llm_client",
        "novelvids.domain.services.storyboard.service",
    ]:
        logging.getLogger(logger_name).setLevel(logging.DEBUG)

    # 降低第三方库的日志级别
    for logger_name in ["httpx", "httpcore", "openai", "tortoise", "aiosqlite", "asyncio", "uvicorn", "uvicorn.access"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    setup_logging()
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info("日志系统已配置，调试模式已启用")
    yield
    logger.info("Shutting down application")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI Novel Video Generator - Generate videos from novels using ComfyUI",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Add middleware
    # app.add_middleware(LoggingMiddleware)
    app.add_middleware(CORSMiddleware, **CORSConfig.get_config())

    # Register routes
    app.include_router(v1_router, prefix="/api")

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.app_version}

    # Register Tortoise ORM
    register_tortoise(
        app,
        config=get_tortoise_config(),
        generate_schemas=True,
        add_exception_handlers=False,
    )

    # Register exception handlers
    from fastapi.exceptions import RequestValidationError
    from tortoise.exceptions import DoesNotExist, IntegrityError
    from novelvids.api.exceptions import AppException
    from novelvids.api.handlers import (
        app_exception_handler,
        global_exception_handler,
        validation_exception_handler,
        integrity_error_handler,
        does_not_exist_handler,
    )

    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(DoesNotExist, does_not_exist_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    # Mount static files for media (images, videos, audio)
    media_path = Path(settings.storage.media_dir)
    media_path.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

    return app


app = create_app()
