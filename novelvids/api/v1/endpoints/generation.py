"""图像、音频和视频生成相关的 API 端点。"""

import base64
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from loguru import logger

from novelvids.api.dependencies import get_current_user_id
from novelvids.application.dto import (
    GenerateVideoDTO,
    ProcessNovelDTO,
    VideoTaskResponseDTO,
)
from novelvids.application.tasks.novel_processing import process_novel_task
from novelvids.core.config import get_settings
from novelvids.domain.models.storyboard import Shot
from novelvids.infrastructure.database.models import ChapterModel, TaskStatus
from novelvids.infrastructure.video_clients import (
    DoubaoClient,
    ViduClient,
    VideoClient,
    VideoTaskStatus,
)
from novelvids.infrastructure.video_clients.base import ReferenceImage

router = APIRouter(prefix="/generate", tags=["视频生成"])


def _get_video_client(platform: str) -> VideoClient:
    """Get the appropriate video client for the platform."""
    settings = get_settings()

    if platform == "vidu":
        if not settings.vidu.api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Vidu API key not configured (set VIDU_API_KEY)",
            )
        return ViduClient(
            api_key=settings.vidu.api_key,
            base_url=settings.vidu.base_url,
            timeout=settings.vidu.timeout,
        )
    elif platform == "doubao":
        if not settings.ark.api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Doubao/Ark API key not configured (set ARK_API_KEY)",
            )
        return DoubaoClient(
            api_key=settings.ark.api_key,
            base_url=settings.ark.base_url,
            model=settings.ark.video_model,
            timeout=settings.ark.timeout,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform: {platform}. Use 'vidu' or 'doubao'.",
        )


async def _get_shot_and_assets(
    chapter_id: UUID, shot_sequence: int
) -> tuple[Shot, list[ReferenceImage], dict[str, str]]:
    """Load shot data and build reference images from chapter assets.
    
    Returns:
        tuple of (shot, reference_images, uuid_to_name_map)
        uuid_to_name_map: mapping from asset UUID to canonical_name for placeholder replacement
    """
    chapter = await ChapterModel.get_or_none(id=chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found",
        )

    storyboard_data = chapter.metadata.get("storyboard")
    if not storyboard_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Storyboard not found for this chapter",
        )

    # Find the specific shot
    shot_data = None
    for s in storyboard_data.get("shots", []):
        if s.get("sequence") == shot_sequence:
            shot_data = s
            break

    if not shot_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot {shot_sequence} not found",
        )

    shot = Shot.model_validate(shot_data)
    logger.info(f"[Video Gen] Shot {shot_sequence}: asset_refs={shot.subject.asset_refs}, scene_ref={shot.environment.scene_asset_ref}")

    # Build reference images from asset_refs
    reference_images: list[ReferenceImage] = []
    uuid_to_name: dict[str, str] = {}
    from novelvids.infrastructure.database.models import AssetModel

    # Collect all asset IDs (subject + scene)
    all_asset_ids = list(shot.subject.asset_refs)
    if shot.environment.scene_asset_ref and shot.environment.scene_asset_ref not in all_asset_ids:
        all_asset_ids.append(shot.environment.scene_asset_ref)

    for asset_id in all_asset_ids:
        asset = await AssetModel.get_or_none(id=asset_id)
        if not asset:
            logger.warning(f"[Video Gen] Asset {asset_id} not found in database")
            continue
        
        # Build UUID -> canonical_name mapping for all assets
        uuid_to_name[str(asset_id)] = asset.canonical_name
        
        if not asset.main_image:
            logger.warning(f"[Video Gen] Asset {asset_id} ({asset.canonical_name}) has no main_image")
            continue

        try:
            # Convert /media/... URL path to filesystem path
            # DB stores: /media/novels/{novel_id}/assets/{asset_id}/filename.jpg
            # Actual path: ./media/novels/{novel_id}/assets/{asset_id}/filename.jpg
            relative_path = asset.main_image.lstrip("/")  # Remove leading /
            image_path = Path(relative_path)
            if not image_path.exists():
                logger.warning(f"[Video Gen] Image file not found: {image_path}")
                continue

            with open(image_path, "rb") as f:
                image_bytes = f.read()

            ext = image_path.suffix.lower()
            mime_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
            mime = mime_types.get(ext, "image/jpeg")
            b64 = base64.b64encode(image_bytes).decode()
            data_url = f"data:{mime};base64,{b64}"

            reference_images.append(
                ReferenceImage(
                    id=asset.canonical_name,
                    image_data=data_url,
                    label=asset.canonical_name,
                )
            )
            logger.info(f"[Video Gen] Loaded reference image: {asset.canonical_name} ({len(image_bytes)} bytes, {mime})")
        except Exception as e:
            logger.error(f"[Video Gen] Failed to load asset image {asset_id} ({asset.canonical_name}): {e}")

    logger.info(f"[Video Gen] Total reference images: {len(reference_images)}, ids: {[r.id for r in reference_images]}")
    logger.info(f"[Video Gen] UUID to name mapping: {uuid_to_name}")
    return shot, reference_images, uuid_to_name



@router.post("/process-novel")
async def process_novel(
    data: ProcessNovelDTO,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    background_tasks: BackgroundTasks,
):
    """开始处理小说以生成视频。"""
    background_tasks.add_task(process_novel_task, data.novel_id, user_id)

    return {
        "task_id": str(data.novel_id),
        "status": TaskStatus.QUEUED.value,
        "message": "小说处理任务已加入队列",
    }


@router.get("/status/{task_id}")
async def get_generation_status(
    task_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
):
    """获取生成任务的状态。"""
    # TODO: 从任务队列中查询实际的任务状态
    return {
        "task_id": str(task_id),
        "status": TaskStatus.PENDING.value,
        "progress": 0,
        "message": "任务等待处理中",
    }


# ============== Video Generation Endpoints ==============


@router.post("/video", response_model=VideoTaskResponseDTO)
async def generate_video(
    data: GenerateVideoDTO,
    # user_id: Annotated[UUID, Depends(get_current_user_id)],
):
    """Start video generation for a storyboard shot.

    Supported platforms: vidu, doubao.
    Returns a task_id for polling status.
    """
    if data.platform not in ("vidu", "doubao"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported platform: {data.platform}. Use 'vidu' or 'doubao'.",
        )

    logger.info(f"[Video Gen] Request: chapter={data.chapter_id}, shot={data.shot_sequence}, platform={data.platform}, duration={data.duration}, aspect_ratio={data.aspect_ratio}")

    # Load shot data and reference images
    shot, reference_images, uuid_to_name = await _get_shot_and_assets(data.chapter_id, data.shot_sequence)

    # Get platform-specific client
    client = _get_video_client(data.platform)

    try:
        # Build prompt: prefer pre-built platform_prompt with {ref:id} placeholders
        if shot.platform_prompt:
            prompt = shot.platform_prompt
            logger.info(f"[Video Gen] Using pre-built platform_prompt: {prompt[:200]}...")
        else:
            prompt = shot.build_prompt(data.platform)
            logger.info(f"[Video Gen] Using fallback build_prompt: {prompt[:200]}...")

        # Replace UUID placeholders with canonical_name placeholders (backwards compatibility)
        # Old format: {ref:f8eda767-09fc-4843-951c-7c64a95f5f6a} -> {ref:崇祯皇帝}
        for uuid_str, name in uuid_to_name.items():
            prompt = prompt.replace(f"{{ref:{uuid_str}}}", f"{{ref:{name}}}")

        # Replace {ref:name} placeholders with platform-specific markers (@name or [图N])
        prompt = client.build_prompt_with_refs(prompt, reference_images)
        negative_prompt = shot.build_negative_prompt()

        logger.info(f"[Video Gen] Final prompt ({len(prompt)} chars): {prompt}")
        logger.info(f"[Video Gen] Negative prompt: {negative_prompt[:200]}...")
        logger.info(f"[Video Gen] Reference images count: {len(reference_images)}, ids: {[r.id for r in reference_images]}")

        # Create video generation task
        task = await client.create_video(
            prompt=prompt,
            reference_images=reference_images,
            duration=data.duration,
            aspect_ratio=data.aspect_ratio,
            negative_prompt=negative_prompt,
        )

        logger.info(f"[Video Gen] Task created: task_id={task.task_id}, status={task.status.value}")

        if task.status == VideoTaskStatus.FAILED:
            logger.error(f"[Video Gen] Task failed immediately: {task.error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Video generation failed: {task.error}",
            )

        # Save task_id to chapter metadata (storyboard -> shots)
        chapter = await ChapterModel.get_or_none(id=data.chapter_id)
        if chapter and chapter.metadata.get("storyboard"):
            storyboard = chapter.metadata["storyboard"]
            for shot_data in storyboard.get("shots", []):
                if shot_data.get("sequence") == data.shot_sequence:
                    shot_data["video_task_id"] = task.task_id
                    shot_data["video_task_platform"] = data.platform
                    shot_data["video_task_status"] = task.status.value
                    shot_data["video_task_progress"] = task.progress
                    shot_data["video_url"] = None
                    shot_data["video_error"] = None
                    break
            chapter.metadata["storyboard"] = storyboard
            await chapter.save()
            logger.info(f"[Video Gen] Saved task_id={task.task_id} to shot {data.shot_sequence}")

        return VideoTaskResponseDTO(
            task_id=task.task_id,
            platform=data.platform,
            status=task.status.value,
            progress=task.progress,
            shot_sequence=data.shot_sequence,
        )

    finally:
        await client.close()


@router.get("/video/{task_id}", response_model=VideoTaskResponseDTO)
async def get_video_task_status(
    task_id: str,
    platform: str = "vidu",
    chapter_id: UUID | None = None,
    shot_sequence: int | None = None,
    user_id: Annotated[UUID, Depends(get_current_user_id)] = None,
):
    """Poll video generation task status.

    Args:
        task_id: The task ID from the generate endpoint
        platform: Which platform this task belongs to (vidu or doubao)
        chapter_id: Optional chapter ID to update shot status in database
        shot_sequence: Optional shot sequence to update
    """
    client = _get_video_client(platform)

    try:
        task = await client.get_task_status(task_id)

        # Update shot status in database if chapter_id and shot_sequence provided
        if chapter_id and shot_sequence:
            chapter = await ChapterModel.get_or_none(id=chapter_id)
            if chapter and chapter.metadata.get("storyboard"):
                storyboard = chapter.metadata["storyboard"]
                for shot_data in storyboard.get("shots", []):
                    if shot_data.get("sequence") == shot_sequence:
                        shot_data["video_task_status"] = task.status.value
                        shot_data["video_task_progress"] = task.progress
                        if task.video_url:
                            shot_data["video_url"] = task.video_url
                        if task.error:
                            shot_data["video_error"] = task.error
                        break
                chapter.metadata["storyboard"] = storyboard
                await chapter.save()
                logger.info(f"[Video Gen] Updated shot {shot_sequence} status: {task.status.value}, progress: {task.progress}")

        return VideoTaskResponseDTO(
            task_id=task.task_id,
            platform=platform,
            status=task.status.value,
            progress=task.progress,
            video_url=task.video_url,
            error=task.error,
            shot_sequence=shot_sequence,
        )

    finally:
        await client.close()


@router.delete("/video/{chapter_id}/{shot_sequence}")
async def cancel_video_task(
    chapter_id: UUID,
    shot_sequence: int,
    user_id: Annotated[UUID, Depends(get_current_user_id)] = None,
):
    """Cancel/clear a video generation task for a shot.

    This clears the task from the database, allowing the user to regenerate.
    Note: This does NOT cancel the task on the remote platform (vidu/doubao).
    """
    chapter = await ChapterModel.get_or_none(id=chapter_id)
    if not chapter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chapter not found",
        )

    storyboard = chapter.metadata.get("storyboard")
    if not storyboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Storyboard not found",
        )

    # Find and clear the shot's video task info
    shot_found = False
    for shot_data in storyboard.get("shots", []):
        if shot_data.get("sequence") == shot_sequence:
            shot_found = True
            old_task_id = shot_data.get("video_task_id")
            shot_data["video_task_id"] = None
            shot_data["video_task_platform"] = None
            shot_data["video_task_status"] = None
            shot_data["video_task_progress"] = 0
            shot_data["video_url"] = None
            shot_data["video_error"] = None
            break

    if not shot_found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shot {shot_sequence} not found",
        )

    chapter.metadata["storyboard"] = storyboard
    await chapter.save()

    logger.info(f"[Video Gen] Cancelled task for shot {shot_sequence}, old task_id={old_task_id}")
    return {"success": True, "message": f"Video task for shot {shot_sequence} cleared"}
