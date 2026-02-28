"""视频控制器 - 生成、查询、CRUD。"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from config import settings
from models.scene import Scene
from models.video import Video
from schemas.video import VideoGenerateRequest
from services.video import get_generator
from services.video.asset_resolver import resolve_assets
from services.video.merge import video_merger
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

logger = logging.getLogger(__name__)


async def _download_video(remote_url: str, video_id: int) -> str:
    """将远程视频下载到本地 MEDIA_PATH/videos/ 目录，返回可访问的 /media/ 路径。"""
    video_dir = os.path.join(settings.MEDIA_PATH, "videos")
    os.makedirs(video_dir, exist_ok=True)

    filename = f"{video_id}.mp4"
    local_path = os.path.join(video_dir, filename)

    logger.info("Video download start: video_id=%s, url=%s", video_id, remote_url[:120])
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("GET", remote_url) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)

    media_url = f"/media/videos/{filename}"
    logger.info("Video downloaded: video_id=%s -> %s", video_id, media_url)
    return media_url


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

        # 查找启用的视频配置
        config = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)

        # 解析 @资产昵称
        prompt = scene.prompt or ""
        subjects = await resolve_assets(prompt, novel_id)
        logger.info(
            "Video resolve_assets: scene_id=%s, novel_id=%s, prompt_len=%d, subjects=%s",
            scene.id, novel_id, len(prompt),
            [(s["name"], len(s.get("images", []))) for s in subjects],
        )

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
            "Video generate: video_id=%s, scene_id=%s, task_id=%s",
            video.id, scene.id, external_task_id,
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

        # 查找启用的视频配置
        config = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)

        generator = get_generator(video.model_type, config)
        result = await generator.query(video.external_task_id)
        logger.info(
            "Video query result: video_id=%s, status=%s, url=%s, metadata=%s",
            video_id, result.get("status"), result.get("url"), result.get("metadata"),
        )

        # 更新 Video 记录
        new_status = result["status"].value
        update_fields = ["status"]

        video.status = new_status

        # 视频完成时，下载到本地替换临时 URL
        remote_url = result.get("url")
        if remote_url:
            try:
                media_url = await _download_video(remote_url, video.id)
                video.url = media_url
                update_fields.append("url")
            except Exception as e:
                logger.error("Video download failed: video_id=%s, error=%s", video_id, e)
                video.metadata = {**(video.metadata or {}), "error": f"视频下载失败: {e}"}
                update_fields.append("metadata")
        elif new_status == TaskStatusEnum.completed.value:
            logger.warning("Video completed but no URL: video_id=%s, result=%s", video_id, result)

        if result.get("metadata"):
            video.metadata = {**(video.metadata or {}), **result["metadata"]}
            if "metadata" not in update_fields:
                update_fields.append("metadata")

        await video.save(update_fields=update_fields)
        return video

    async def remove(self, video_id: int) -> None:
        instance = await self.get(video_id)
        await super().remove(instance)

    async def get_chapter_videos(self, chapter_id: int) -> list[dict]:
        """获取章节下所有分镜的视频，按 scene.sequence 排序。

        Returns:
            [
                {
                    "scene_id": 1,
                    "sequence": 1,
                    "description": "镜头描述",
                    "duration": 4.0,
                    "video": {
                        "id": 10,
                        "url": "/media/videos/10.mp4",
                        "status": 3,
                        "model_type": 4
                    } | None
                },
                ...
            ]
        """
        # 查询该章节的所有分镜，按 sequence 排序
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")

        result = []
        for scene in scenes:
            # 获取该分镜最新的已完成视频
            video = await Video.filter(
                scene_id=scene.id,
                status=TaskStatusEnum.completed.value
            ).order_by("-id").first()

            item = {
                "scene_id": scene.id,
                "sequence": scene.sequence,
                "description": scene.description,
                "duration": scene.duration,
                "video": None
            }

            if video:
                item["video"] = {
                    "id": video.id,
                    "url": video.url,
                    "status": video.status,
                    "model_type": video.model_type
                }

            result.append(item)

        return result

    async def get_novel_videos(self, novel_id: int) -> list[dict]:
        """获取小说下所有视频。

        Args:
            novel_id: 小说 ID

        Returns:
            [
                {
                    "id": 10,
                    "url": "/media/videos/10.mp4",
                    "status": 3,
                    "model_type": 4
                },
                ...
            ]
        """
        videos = await Video.filter(
            scene__chapter__novel_id=novel_id
        ).order_by("-created_at")
        return [
        {
            "id": video.id,
            "url": video.url,
            "status": video.status,
            "model_type": video.model_type
        }
        for video in videos
    ]

    async def merge_chapter_videos(self, chapter_id: int) -> dict:
        """合并章节下所有已完成的视频。

        Args:
            chapter_id: 章节 ID

        Returns:
            {
                "chapter_id": 123,
                "merged_url": "/media/videos/merged/chapter_123_merged.mp4",
                "video_count": 5,
                "total_duration": 45.0
            }
        """
        # 获取章节所有分镜
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")

        # 收集所有已完成视频，同时检查是否有分镜缺少视频
        videos_to_merge: list[Video] = []
        total_duration = 0.0
        missing_scenes: list[int] = []

        for scene in scenes:
            video = await Video.filter(
                scene_id=scene.id,
                status=TaskStatusEnum.completed.value
            ).order_by("-id").first()

            if video:
                videos_to_merge.append(video)
                total_duration += scene.duration or 0
            else:
                missing_scenes.append(scene.sequence)

        # 检查是否所有分镜都有视频
        if missing_scenes:
            raise HTTPException(
                400,
                detail=f"以下分镜尚未生成视频，无法合并：分镜 #{', '.join(map(str, missing_scenes))}"
            )

        # 调用合并服务
        try:
            merged_url = video_merger.merge_videos(videos_to_merge, chapter_id)
        except ValueError as e:
            raise HTTPException(400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(500, detail=str(e))

        return {
            "chapter_id": chapter_id,
            "merged_url": merged_url,
            "video_count": len(videos_to_merge),
            "total_duration": round(total_duration, 1)
        }

    async def get_merged_video(self, chapter_id: int) -> dict | None:
        """查询章节是否已有合并好的视频。

        Args:
            chapter_id: 章节 ID

        Returns:
            如果存在返回合并信息，否则返回 None
        """
        merged_dir = os.path.join(settings.MEDIA_PATH, "videos", "merged")
        filename = f"chapter_{chapter_id}_merged.mp4"
        file_path = os.path.join(merged_dir, filename)

        if not os.path.exists(file_path):
            return None

        # 获取该章节的视频统计
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")
        video_count = 0
        total_duration = 0.0

        for scene in scenes:
            video = await Video.filter(
                scene_id=scene.id,
                status=TaskStatusEnum.completed.value
            ).order_by("-id").first()
            if video:
                video_count += 1
                total_duration += scene.duration or 0

        return {
            "chapter_id": chapter_id,
            "merged_url": f"/media/videos/merged/{filename}",
            "video_count": video_count,
            "total_duration": round(total_duration, 1)
        }


video_controller = VideoController()
