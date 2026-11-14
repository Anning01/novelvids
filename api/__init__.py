from fastapi import APIRouter

from api.diagnostics import router as diagnostics_router
from api.ai_task import router as ai_task_router
from api.asset import router as asset_router
from api.billing import router as billing_router
from api.config import router as config_router
from api.novel import router as novel_router
from api.chapter import router as chapter_router
from api.file import router as file_router
from api.scene import router as scene_router
from api.video import router as video_router
from api.video_export import router as video_export_router
from api.media_library import router as media_library_router
from api.workbench import router as workbench_router
from api.remake import router as remake_router
from api.creation_agent import router as creation_agent_router

from api.resource_library import router as resource_library_router
from api.resource_catalog import router as resource_catalog_router
from api.video_edit import router as video_edit_router

from api.portfolio import router as portfolio_router
from api.finished_episode import router as finished_episode_router
from api.experience import router as experience_router

from api.release import router as release_router

api_router = APIRouter()
api_router.include_router(release_router, prefix="/release", tags=["工作台版本"])
api_router.include_router(diagnostics_router, prefix="/diagnostics", tags=["诊断日志"])
api_router.include_router(experience_router, prefix="/experience", tags=["模型体验与优秀作品"])
api_router.include_router(portfolio_router, prefix="/portfolio", tags=["作品库"])
api_router.include_router(finished_episode_router, prefix='/finished-episodes', tags=['作品库'])
api_router.include_router(resource_catalog_router, prefix='/resource-library/catalog', tags=['团队资源库'])
api_router.include_router(video_edit_router, prefix='/video-editor', tags=['视频剪辑'])
api_router.include_router(resource_library_router, prefix="/resource-library", tags=["团队视频资源库"])


api_router.include_router(novel_router, prefix="/novel", tags=["小说/剧本管理"])
api_router.include_router(chapter_router, prefix="/chapter", tags=["章节管理"])
api_router.include_router(scene_router, prefix="/scene", tags=["分镜管理"])
api_router.include_router(asset_router, prefix="/asset", tags=["资产管理"])
api_router.include_router(ai_task_router, prefix="/task", tags=["AI 任务"])
api_router.include_router(config_router, prefix="/config", tags=["模型配置"])
api_router.include_router(file_router, prefix="/file", tags=["文件管理"])
api_router.include_router(video_export_router, prefix="/video/exports", tags=["成片导出"])
api_router.include_router(video_router, prefix="/video", tags=["视频生成"])
api_router.include_router(media_library_router, prefix="/media-library", tags=["媒体资源库"])
api_router.include_router(workbench_router, prefix="/workbench", tags=["创作画布"])
api_router.include_router(billing_router, prefix="/billing", tags=["账单计费"])
api_router.include_router(remake_router, prefix="/remake", tags=["重制工坊"])
api_router.include_router(creation_agent_router, prefix="/creation-agent", tags=["创作助手"])
