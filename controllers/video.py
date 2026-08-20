"""视频控制器 - 生成、查询、CRUD。"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from config import settings
from models.scene import Scene
from models.chapter import Chapter
from models.video import Video
from schemas.video import VideoGenerateRequest
from services.billing.recorder import billing_recorder
from services.video import get_generator
from services.video.base import VideoProviderError
from services.video.asset_resolver import (
    normalize_selected_variant_ids,
    resolve_assets,
    resolve_image_source,
)
from services.video.capabilities import validate_selection
from services.video.capabilities import capabilities_for
from services.video.reference_media import (
    render_reference_mentions,
    select_referenced_media,
    verify_local_reference,
)
from services.video.merge import video_merger
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, VideoModelTypeEnum

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
    from services.oss import make_upload_key, oss

    if oss.enabled:
        with open(local_path, "rb") as file:
            key = make_upload_key(None, f"videos/{filename}")
            await oss.put_bytes(key, file.read(), "video/mp4")
        os.remove(local_path)
        # 落库存 key，读取时再由 resolve_media_url 重新签发临时 URL
        media_url = key
    logger.info("Video downloaded: video_id=%s -> %s", video_id, media_url)
    return media_url


async def _download_last_frame(remote_url: str, video_id: int) -> str:
    """持久化供应商尾帧，避免下一镜头生成时引用临时 URL。"""
    directory = Path(settings.MEDIA_PATH) / "video-references"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"last-frame-{video_id}.png"
    temporary = directory / f".last-frame-{video_id}.downloading"
    size_bytes = 0
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("GET", remote_url) as response:
                response.raise_for_status()
                with temporary.open("wb") as target:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        size_bytes += len(chunk)
                        if size_bytes > 30 * 1024 * 1024:
                            raise ValueError("尾帧图片超过 30MB")
                        target.write(chunk)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    from services.oss import make_upload_key, oss

    if oss.enabled:
        with open(destination, "rb") as file:
            key = make_upload_key(None, f"video-references/last-frame-{video_id}.png")
            await oss.put_bytes(key, file.read(), "image/png")
        destination.unlink(missing_ok=True)
        # 落库存 key，读取时再由 resolve_media_url 重新签发临时 URL
        return key
    return f"/media/video-references/{destination.name}"


async def _next_scene(scene: Scene) -> Scene | None:
    """按小说章节与镜头顺序找到下一镜头，章节末尾自动跨到下一章。"""
    next_in_chapter = await Scene.filter(
        chapter_id=scene.chapter_id,
        sequence__gt=scene.sequence,
    ).order_by("sequence", "id").first()
    if next_in_chapter is not None:
        return next_in_chapter

    chapter = await Chapter.get(id=scene.chapter_id)
    next_chapter = await Chapter.filter(
        novel_id=chapter.novel_id,
        number__gt=chapter.number,
    ).order_by("number", "id").first()
    if next_chapter is None:
        return None
    return await Scene.filter(chapter_id=next_chapter.id).order_by("sequence", "id").first()


async def _inject_last_frame_reference(video: Video, last_frame_url: str) -> dict | None:
    """将尾帧写入下一镜头 metadata.video_reference_media，保持操作幂等。"""
    source_scene = await Scene.get(id=video.scene_id)
    target_scene = await _next_scene(source_scene)
    if target_scene is None:
        return None

    reference = {
        "type": "image",
        "url": last_frame_url,
        "name": f"分镜{source_scene.sequence}生成尾帧.png",
        "content_type": "image/png",
        "source": "previous_scene_last_frame",
        "source_scene_id": source_scene.id,
        "source_video_id": video.id,
    }
    target_metadata = target_scene.metadata if isinstance(target_scene.metadata, dict) else {}
    raw_media = target_metadata.get("video_reference_media")
    media = [item for item in raw_media if isinstance(item, dict)] if isinstance(raw_media, list) else []
    media = [
        item for item in media
        if not (
            item.get("source") == "previous_scene_last_frame"
            and item.get("source_scene_id") == source_scene.id
        )
    ]
    target_scene.metadata = {**target_metadata, "video_reference_media": [reference, *media]}
    await target_scene.save(update_fields=["metadata", "updated_at"])
    return {"scene_id": target_scene.id, "reference": reference}


class VideoController(CRUDBase[Video, dict, dict]):
    def __init__(self):
        super().__init__(model=Video)

    @staticmethod
    async def _set_scene_current_video(scene: Scene, video_id: int) -> None:
        """记录分镜当前展示的视频版本，不覆盖其他分镜元数据。"""
        current_scene = await Scene.get(id=scene.id)
        metadata = current_scene.metadata if isinstance(current_scene.metadata, dict) else {}
        current_scene.metadata = {**metadata, "current_video_id": video_id}
        await current_scene.save(update_fields=["metadata", "updated_at"])

    async def generation_history(self, scene_id: int) -> list[Video]:
        """返回分镜的全部视频生成版本，最新记录在前。"""
        if not await Scene.exists(id=scene_id):
            raise HTTPException(404, detail=f"分镜 {scene_id} 不存在")
        return await Video.filter(scene_id=scene_id).order_by("-id")

    async def select_current(self, video_id: int) -> Video:
        """将已完成的视频历史版本恢复为分镜当前版本。"""
        video = await self.get(video_id)
        if video.status != TaskStatusEnum.completed.value or not video.url:
            raise HTTPException(400, detail="只有已完成且包含视频文件的记录可以设为当前版本")
        scene = await Scene.get(id=video.scene_id)
        await self._set_scene_current_video(scene, video.id)
        return video

    async def generate(
        self,
        req: VideoGenerateRequest,
        media_base_url: str = "",
        team_id: int | None = None,
        user_id: int | None = None,
    ) -> Video:
        """提交视频生成请求。

        1. 获取 Scene (含关联 chapter -> novel)
        2. 根据 model_config_id 查找用户已启用的 AiModelConfig
        3. 解析 prompt 中的 @资产昵称 -> subjects
        4. 调用生成器 submit()
        5. 创建 Video 记录 (status=pending)
        """
        scene = await Scene.get_or_none(id=req.scene_id)
        if not scene:
            raise HTTPException(404, detail=f"分镜 {req.scene_id} 不存在")

        # 获取 novel_id (通过 chapter)
        # SQLite 测试和开发环境使用单连接；分开预取，避免并发 relation 查询争用连接。
        await scene.fetch_related("chapter")
        await scene.fetch_related("assets")
        novel_id = scene.chapter.novel_id

        # 查找启用的视频配置（团队自定义优先，官方兜底）
        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.video.value,
            req.model_config_id,
            team_id=team_id,
        )

        # 解析 @资产昵称，并采用分镜中显式选择的资产衍生状态。
        prompt = scene.prompt or ""
        metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
        subjects = await resolve_assets(
            prompt,
            novel_id,
            chapter_number=scene.chapter.number,
            selected_asset_ids=[asset.id for asset in scene.assets],
            selected_variant_ids=normalize_selected_variant_ids(
                metadata.get("asset_variant_ids")
            ),
        )
        logger.info(
            "Video resolve_assets: scene_id=%s, novel_id=%s, prompt_len=%d, subjects=%s",
            scene.id, novel_id, len(prompt),
            [(s["name"], len(s.get("images", []))) for s in subjects],
        )

        # 获取生成器并提交
        generator = get_generator(config)
        duration = req.duration if req.duration is not None else int(scene.duration or 6)
        selection = validate_selection(
            config.video_model_type,
            generation_mode=req.generation_mode,
            resolution=req.resolution,
            aspect_ratio=req.aspect_ratio,
            duration=duration,
            output_format=req.output_format,
            generate_audio=req.generate_audio,
            return_last_frame=req.return_last_frame,
        )
        if req.generation_mode == "keyframes" and not (req.first_frame_url and req.last_frame_url):
            raise HTTPException(400, detail="首尾帧模式必须同时上传首帧和尾帧")
        if req.generation_mode == "keyframes" and req.reference_media:
            raise HTTPException(400, detail="首尾帧模式不能同时使用全模态参考素材")
        first_frame = req.first_frame_url
        last_frame = req.last_frame_url
        if req.generation_mode == "keyframes":
            try:
                first_frame = resolve_image_source(req.first_frame_url or "")
                last_frame = resolve_image_source(req.last_frame_url or "")
            except FileNotFoundError as error:
                raise HTTPException(400, detail=f"首尾帧图片不存在：{error}") from error
        capabilities = capabilities_for(config.video_model_type)
        reference_images: list[str] = []
        reference_videos: list[str] = []
        reference_video_duration = 0.0
        seen_references: set[tuple[str, str]] = set()
        referenced_media = select_referenced_media(prompt, req.reference_media)
        provider_prompt = render_reference_mentions(prompt, referenced_media)
        logger.info(
            "Video reference filter: scene_id=%s, supplied=%d, referenced=%d",
            scene.id,
            len(req.reference_media),
            len(referenced_media),
        )
        for reference in referenced_media:
            identity = (reference.type, reference.url)
            if identity in seen_references:
                continue
            seen_references.add(identity)
            verified = await verify_local_reference(reference.type, reference.url, capabilities)
            if reference.type == "image":
                try:
                    reference_images.append(resolve_image_source(reference.url))
                except FileNotFoundError as error:
                    raise HTTPException(400, detail=f"参考图片不存在：{error}") from error
                continue
            duration_value = (verified or {}).get("duration") or reference.duration
            if not duration_value:
                raise HTTPException(400, detail="无法校验参考视频时长，请重新上传该视频")
            reference_video_duration += float(duration_value)
            if reference.url.startswith("/media/"):
                if not media_base_url:
                    raise HTTPException(400, detail="本地参考视频缺少可访问的媒体地址")
                reference_videos.append(f"{media_base_url}{reference.url}")
            else:
                reference_videos.append(reference.url)

        asset_reference_image_count = sum(len(subject.get("images", [])) for subject in subjects)
        if asset_reference_image_count + len(reference_images) > capabilities.max_reference_images:
            raise HTTPException(
                400,
                detail=(
                    f"当前模型最多接收 {capabilities.max_reference_images} 张参考图片，"
                    "已包含分镜所选资产图"
                ),
            )
        if len(reference_videos) > capabilities.max_reference_videos:
            raise HTTPException(400, detail=f"当前模型最多接收 {capabilities.max_reference_videos} 个参考视频")
        if reference_video_duration > capabilities.reference_video_total_duration_max + 0.001:
            raise HTTPException(
                400,
                detail=f"当前模型参考视频总时长不能超过 {capabilities.reference_video_total_duration_max} 秒",
            )
        video_metadata = {
            "generation_mode": req.generation_mode,
            "first_frame_url": req.first_frame_url,
            "last_frame_url": req.last_frame_url,
            "model_config_id": config.id,
            "novel_id": novel_id,
            "has_video_reference": len(reference_videos) > 0,
            "input_video_seconds": reference_video_duration,
            "model_name": config.name,
            "model": config.model,
            "video_model_type": config.video_model_type,
            "resolution": selection.resolution,
            "aspect_ratio": selection.aspect_ratio,
            "duration": selection.duration,
            "output_format": selection.output_format,
            "generate_audio": selection.generate_audio,
            "return_last_frame": selection.return_last_frame,
            "reference_media": [item.model_dump() for item in referenced_media],
        }
        if team_id is not None:
            video_metadata["team_id"] = team_id
        if user_id is not None:
            video_metadata["user_id"] = user_id
        try:
            external_task_id = await generator.submit(
                prompt=provider_prompt,
                subjects=subjects if subjects and req.generation_mode == "reference" else None,
                duration=selection.duration,
                aspect_ratio=selection.aspect_ratio,
                resolution=selection.resolution,
                output_format=selection.output_format,
                generate_audio=selection.generate_audio,
                generation_mode=req.generation_mode,
                first_frame_url=first_frame,
                last_frame_url=last_frame,
                reference_images=reference_images,
                reference_videos=reference_videos,
                return_last_frame=selection.return_last_frame,
            )
        except VideoProviderError as error:
            # 供应商在提交阶段直接拒绝请求时也创建失败记录，让异常在预览区可见，
            # 并使分镜状态在刷新页面后仍保持为红色。
            video = await Video.create(
                scene_id=scene.id,
                model_type=VideoModelTypeEnum.seedance.value,
                external_task_id=None,
                status=TaskStatusEnum.failed.value,
                metadata={**video_metadata, "error": str(error)},
            )
            await self._set_scene_current_video(scene, video.id)
            logger.warning(
                "Video submit rejected: video_id=%s, scene_id=%s, model_config_id=%s",
                video.id,
                scene.id,
                config.id,
            )
            return video

        # 创建 Video 记录
        video = await Video.create(
            scene_id=scene.id,
            model_type=VideoModelTypeEnum.seedance.value,
            external_task_id=external_task_id,
            status=TaskStatusEnum.pending.value,
            metadata=video_metadata,
        )
        await self._set_scene_current_video(scene, video.id)
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

        # 新记录保存了配置 ID：即使管理员之后停用它，也要用原配置完成状态查询。
        # 历史记录没有配置 ID 时，继续回退到当前启用配置。
        # 团队作用域从视频元数据读取（生成时固化）。
        metadata = video.metadata or {}
        team_id = metadata.get("team_id")
        config_id = metadata.get("model_config_id")
        if config_id is not None:
            config = await ai_model_config_controller.get_configured_for_task(
                AiTaskTypeEnum.video.value,
                int(config_id),
                team_id=team_id,
            )
        else:
            config = await ai_model_config_controller.get_active(
                AiTaskTypeEnum.video.value, team_id=team_id
            )

        generator = get_generator(config)
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

        result_metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
        provider_last_frame_url = result_metadata.get("last_frame_url")
        if (
            new_status == TaskStatusEnum.completed.value
            and (video.metadata or {}).get("return_last_frame") is True
            and isinstance(provider_last_frame_url, str)
            and provider_last_frame_url
        ):
            persisted_last_frame_url = provider_last_frame_url
            try:
                persisted_last_frame_url = await _download_last_frame(provider_last_frame_url, video.id)
            except Exception as error:
                logger.warning(
                    "Last frame download failed; preserving provider URL: video_id=%s, error=%s",
                    video.id,
                    error,
                )
            try:
                propagation = await _inject_last_frame_reference(video, persisted_last_frame_url)
                video.metadata = {
                    **(video.metadata or {}),
                    "last_frame_url": persisted_last_frame_url,
                    "last_frame_injected_scene_id": propagation["scene_id"] if propagation else None,
                    "last_frame_reference": propagation["reference"] if propagation else None,
                }
            except Exception as error:
                logger.exception("Last frame propagation failed: video_id=%s", video.id)
                video.metadata = {
                    **(video.metadata or {}),
                    "last_frame_url": persisted_last_frame_url,
                    "last_frame_propagation_error": str(error)[:300],
                }
            if "metadata" not in update_fields:
                update_fields.append("metadata")

        try:
            if metadata.get("novel_id") is not None:
                duration_seconds = None
                if video.created_at:
                    duration_seconds = max(0.0, (datetime.now(timezone.utc) - video.created_at).total_seconds())
                if new_status == TaskStatusEnum.completed.value:
                    seconds = result_metadata.get("duration") or metadata.get("duration")
                    record = await billing_recorder.record_video(
                        novel_id=metadata.get("novel_id"),
                        model_config_id=metadata.get("model_config_id"),
                        seconds=seconds,
                        resolution=metadata.get("resolution"),
                        input_video_seconds=metadata.get("input_video_seconds", 0),
                        has_video_reference=metadata.get("has_video_reference", False),
                        status=TaskStatusEnum.completed.value,
                        duration_seconds=duration_seconds,
                        video_id=video.id,
                        team_id=metadata.get("team_id"),
                        user_id=metadata.get("user_id"),
                    )
                    await self._consume_balance(record, metadata.get("team_id"), user_id=metadata.get("user_id"))
                elif new_status in (TaskStatusEnum.failed.value, TaskStatusEnum.cancelled.value):
                    record = await billing_recorder.record_video(
                        novel_id=metadata.get("novel_id"),
                        model_config_id=metadata.get("model_config_id"),
                        seconds=0.0,
                        resolution=metadata.get("resolution"),
                        input_video_seconds=metadata.get("input_video_seconds", 0),
                        has_video_reference=metadata.get("has_video_reference", False),
                        status=TaskStatusEnum.failed.value,
                        duration_seconds=duration_seconds,
                        video_id=video.id,
                        team_id=metadata.get("team_id"),
                        user_id=metadata.get("user_id"),
                    )
                    await self._consume_balance(record, metadata.get("team_id"), user_id=metadata.get("user_id"))
        except Exception:
            logger.exception("billing record failed for video %s", video.id)

        await video.save(update_fields=update_fields)
        return video

    @staticmethod
    async def _consume_balance(record, team_id, user_id=None) -> None:
        if record is None or team_id is None:
            return
        from services.balance import accumulate_member_cost, consume

        # 团队自己的 Key 不扣团队余额；成员累计消耗照记
        if record.cost_source != "team_key":
            await consume(team_id, record.cost, usage_record_id=record.id)
        await accumulate_member_cost(team_id, user_id, record.cost)

    async def remove(self, video_id: int) -> None:
        instance = await self.get(video_id)
        scene = await Scene.get_or_none(id=instance.scene_id)
        await super().remove(instance)
        if scene is None:
            return
        metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
        if metadata.get("current_video_id") != video_id:
            return
        fallback = await Video.filter(scene_id=scene.id).order_by("-id").first()
        next_metadata = {**metadata}
        if fallback:
            next_metadata["current_video_id"] = fallback.id
        else:
            next_metadata.pop("current_video_id", None)
        scene.metadata = next_metadata
        await scene.save(update_fields=["metadata", "updated_at"])

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
            # 优先使用用户从生成记录中选定的版本，再回退到最新完成版本。
            metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
            current_video_id = metadata.get("current_video_id")
            video = None
            if isinstance(current_video_id, int):
                video = await Video.filter(
                    id=current_video_id,
                    scene_id=scene.id,
                    status=TaskStatusEnum.completed.value,
                ).first()
            if video is None:
                video = await Video.filter(
                    scene_id=scene.id,
                    status=TaskStatusEnum.completed.value,
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
            metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
            current_video_id = metadata.get("current_video_id")
            video = None
            if isinstance(current_video_id, int):
                video = await Video.filter(
                    id=current_video_id,
                    scene_id=scene.id,
                    status=TaskStatusEnum.completed.value,
                ).first()
            if video is None:
                video = await Video.filter(
                    scene_id=scene.id,
                    status=TaskStatusEnum.completed.value,
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
