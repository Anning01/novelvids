"""视频控制器 - 生成、查询、CRUD。"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import HTTPException

from config import settings
from models.config import AiModelConfig
from models.scene import Scene
from models.video import Video
from schemas.video import VideoGenerateRequest
from services.video import get_generator
from services.video.asset_resolver import resolve_assets
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, VideoModelTypeEnum

logger = logging.getLogger(__name__)


async def _download_video(remote_url: str, video_id: int) -> str:
    """将远程视频下载到本地 MEDIA_PATH/videos/ 目录，返回本地路径。"""
    video_dir = os.path.join(settings.MEDIA_PATH, "videos")
    os.makedirs(video_dir, exist_ok=True)

    filename = f"{video_id}.mp4"
    local_path = os.path.join(video_dir, filename)

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("GET", remote_url) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)

    logger.info("Video downloaded: video_id=%s -> %s", video_id, local_path)
    return local_path


class VideoController(CRUDBase[Video, dict, dict]):
    def __init__(self):
        super().__init__(model=Video)

    async def generate(self, req: VideoGenerateRequest) -> Video:
        """提交视频生成请求。

        1. 获取 Scene (含关联 chapter -> novel)
        2. 根据 model_type 查找启用的 AiModelConfig
        3. 解析 prompt 中的 @资产昵称 -> subjects
        4. 调用生成器 submit()
        5. 创建 Video 记录 (status=pending)
        """
        scene = await Scene.get_or_none(id=req.scene_id)
        if not scene:
            raise HTTPException(404, detail=f"分镜 {req.scene_id} 不存在")

        # 获取 novel_id (通过 chapter)
        await scene.fetch_related("chapter")
        novel_id = scene.chapter.novel_id

        # 查找对应平台的配置
        model_name = VideoModelTypeEnum(req.model_type).name
        config = await AiModelConfig.get_or_none(
            task_type=AiTaskTypeEnum.video.value,
            name=model_name,
            is_active=True,
        )
        if not config:
            raise HTTPException(
                404,
                detail=f"视频模型 {model_name} 未配置或未启用",
            )

        # 解析 @资产昵称
        prompt = scene.prompt or ""
        subjects = await resolve_assets(prompt, novel_id)

        # 获取生成器并提交
        generator = get_generator(req.model_type, config)
        duration = scene.duration or 6.0
        external_task_id = await generator.submit(
            prompt=prompt,
            subjects=subjects if subjects else None,
            duration=duration,
        )

        # 创建 Video 记录
        video = await Video.create(
            scene_id=scene.id,
            model_type=req.model_type,
            external_task_id=external_task_id,
            status=TaskStatusEnum.pending.value,
        )
        logger.info(
            "Video generate: video_id=%s, scene_id=%s, model=%s, task_id=%s",
            video.id, scene.id, model_name, external_task_id,
        )
        return video

    async def query_status(self, video_id: int) -> Video:
        """查询视频生成状态，如有变化则更新 Video 记录。"""
        video = await self.get(video_id)

        # 已完成或已失败的不再查询
        if video.status in (
            TaskStatusEnum.completed.value,
            TaskStatusEnum.failed.value,
        ):
            return video

        if not video.external_task_id:
            raise HTTPException(400, detail="该视频无外部任务ID，无法查询")

        # 查找配置
        model_name = VideoModelTypeEnum(video.model_type).name
        config = await AiModelConfig.get_or_none(
            task_type=AiTaskTypeEnum.video.value,
            name=model_name,
            is_active=True,
        )
        if not config:
            raise HTTPException(404, detail=f"视频模型 {model_name} 配置不存在")

        generator = get_generator(video.model_type, config)
        result = await generator.query(video.external_task_id)

        # 更新 Video 记录
        new_status = result["status"].value
        update_fields = ["status"]

        video.status = new_status

        # 视频完成时，下载到本地替换临时 URL
        remote_url = result.get("url")
        if remote_url:
            local_path = await _download_video(remote_url, video.id)
            video.url = local_path
            update_fields.append("url")

        if result.get("metadata"):
            video.metadata = result["metadata"]
            update_fields.append("metadata")

        await video.save(update_fields=update_fields)
        return video

    async def remove(self, video_id: int) -> None:
        instance = await self.get(video_id)
        await super().remove(instance)


video_controller = VideoController()
