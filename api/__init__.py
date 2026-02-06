from fastapi import APIRouter

from api.ai_task import router as ai_task_router
from api.asset import router as asset_router
from api.config import router as config_router
from api.novel import router as novel_router
from api.chapter import router as chapter_router
from api.file import router as file_router

api_router = APIRouter()


api_router.include_router(novel_router, prefix="/novel", tags=["小说/剧本管理"])
api_router.include_router(chapter_router, prefix="/chapter", tags=["章节管理"])
api_router.include_router(asset_router, prefix="/asset", tags=["资产管理"])
api_router.include_router(ai_task_router, prefix="/task", tags=["AI 任务"])
api_router.include_router(config_router, prefix="/config", tags=["模型配置"])
api_router.include_router(file_router, prefix="/file", tags=["文件管理"])
