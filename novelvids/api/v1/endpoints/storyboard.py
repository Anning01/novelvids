"""分镜 API 接口。

使用任务模式进行分镜生成，支持轮询查询进度。
"""

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from novelvids.api.dependencies import get_current_user
from novelvids.application.services.storyboard_task_service import storyboard_task_service
from novelvids.domain.models.storyboard import Shot
from novelvids.domain.services.storyboard import create_storyboard_service
from novelvids.domain.services.storyboard.prompts import SUPPORTED_VIDEO_PLATFORMS
from novelvids.core.config.settings import get_settings
from novelvids.infrastructure.database.models import (
    ChapterModel,
    StoryboardTaskModel,
    TaskStatus,
    UserModel,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/storyboard", tags=["分镜"])


# ============== DTO ==============


class StoryboardGenerateDTO(BaseModel):
    """分镜生成请求 DTO。"""

    max_shot_duration: float = Field(default=8.0, ge=4.0, le=15.0, description="单个镜头最大时长")
    target_platform: str = Field(default="vidu", description="目标平台：vidu/doubao")
    style_preset: str = Field(default="cinematic", description="风格预设")
    aspect_ratio: str = Field(default="16:9", description="画面比例")
    include_audio: bool = Field(default=True, description="是否包含音频指令")


class TaskResponseDTO(BaseModel):
    """任务响应 DTO。"""

    id: UUID
    chapter_id: UUID
    status: str
    progress: int
    message: str | None
    error: str | None = None
    result: dict | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None

    class Config:
        from_attributes = True


class ShotUpdateDTO(BaseModel):
    """分镜更新 DTO。"""

    name: str | None = None
    description_cn: str | None = None
    camera: dict | None = None
    subject: dict | None = None
    environment: dict | None = None
    style: dict | None = None
    audio: dict | None = None
    technical: dict | None = None
    negative: dict | None = None
    transition_in: str | None = None
    transition_out: str | None = None


class StoryboardResponseDTO(BaseModel):
    """分镜响应 DTO。"""

    chapter_id: UUID
    chapter_number: int
    chapter_title: str
    shots: list[dict]
    total_duration: float
    shot_count: int

    class Config:
        from_attributes = True


class ShotPromptDTO(BaseModel):
    """分镜提示词响应 DTO。"""

    sequence: int
    prompt: str
    negative_prompt: str
    platform: str


class StoryboardPromptsDTO(BaseModel):
    """完整分镜提示词响应 DTO。"""

    chapter_id: UUID
    platform: str
    prompts: list[ShotPromptDTO]


# ============== 辅助函数 ==============


def _task_to_dto(task: StoryboardTaskModel) -> TaskResponseDTO:
    """将任务模型转换为 DTO。"""
    return TaskResponseDTO(
        id=task.id,
        chapter_id=task.chapter_id,
        status=task.status.value,
        progress=task.progress,
        message=task.message,
        error=task.error,
        result=task.result,
        created_at=task.created_at.isoformat(),
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


async def _verify_chapter_access(chapter_id: UUID, current_user: UserModel) -> ChapterModel:
    """验证章节访问权限。"""
    chapter = await ChapterModel.filter(id=chapter_id).prefetch_related("novel").first()
    if not chapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

    novel = await chapter.novel
    if novel.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return chapter


# ============== 任务 API 端点 ==============


@router.post("/chapters/{chapter_id}/generate", response_model=TaskResponseDTO)
async def start_generate_storyboard(
    chapter_id: UUID,
    request: StoryboardGenerateDTO,
    background_tasks: BackgroundTasks,
    current_user: UserModel = Depends(get_current_user),
):
    """启动分镜生成任务。

    返回任务ID，前端通过轮询 GET /tasks/{task_id} 查询进度。
    
    仅支持 vidu 和 doubao 平台。
    """
    # 验证平台
    if request.target_platform not in SUPPORTED_VIDEO_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的平台: {request.target_platform}，仅支持: {SUPPORTED_VIDEO_PLATFORMS}",
        )

    await _verify_chapter_access(chapter_id, current_user)

    # 创建任务
    task = await storyboard_task_service.create_task(
        chapter_id=chapter_id,
        target_platform=request.target_platform,
        max_shot_duration=request.max_shot_duration,
        style_preset=request.style_preset,
        aspect_ratio=request.aspect_ratio,
        include_audio=request.include_audio,
    )

    # 如果是新任务，启动后台执行
    if task.status == TaskStatus.PENDING:
        background_tasks.add_task(storyboard_task_service.execute_task, task.id)

    return _task_to_dto(task)


@router.get("/tasks/{task_id}", response_model=TaskResponseDTO)
async def get_task_status(
    task_id: UUID,
    current_user: UserModel = Depends(get_current_user),
):
    """获取分镜生成任务状态。"""
    task = await storyboard_task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    # 验证权限
    await _verify_chapter_access(task.chapter_id, current_user)

    return _task_to_dto(task)


@router.get("/chapters/{chapter_id}/task", response_model=TaskResponseDTO | None)
async def get_chapter_task(
    chapter_id: UUID,
    current_user: UserModel = Depends(get_current_user),
):
    """获取章节的最新分镜生成任务。"""
    await _verify_chapter_access(chapter_id, current_user)

    task = await storyboard_task_service.get_chapter_task(chapter_id)
    if not task:
        return None

    return _task_to_dto(task)


# ============== 分镜数据 API 端点 ==============


@router.get("/chapters/{chapter_id}", response_model=StoryboardResponseDTO)
async def get_storyboard(
    chapter_id: UUID,
    current_user: UserModel = Depends(get_current_user),
):
    """获取章节的分镜脚本。"""
    chapter = await _verify_chapter_access(chapter_id, current_user)

    storyboard_data = chapter.metadata.get("storyboard")

    # 没有分镜时返回空数组
    if not storyboard_data:
        return StoryboardResponseDTO(
            chapter_id=chapter_id,
            chapter_number=chapter.number,
            chapter_title=chapter.title,
            shots=[],
            total_duration=0,
            shot_count=0,
        )

    return StoryboardResponseDTO(
        chapter_id=chapter_id,
        chapter_number=chapter.number,
        chapter_title=chapter.title,
        shots=storyboard_data.get("shots", []),
        total_duration=storyboard_data.get("total_duration", 0),
        shot_count=len(storyboard_data.get("shots", [])),
    )


@router.put("/chapters/{chapter_id}/shots/{sequence}", response_model=dict)
async def update_shot(
    chapter_id: UUID,
    sequence: int,
    update: ShotUpdateDTO,
    current_user: UserModel = Depends(get_current_user),
):
    """更新单个分镜。"""
    chapter = await _verify_chapter_access(chapter_id, current_user)

    storyboard_data = chapter.metadata.get("storyboard")
    if not storyboard_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyboard not found")

    # 查找并更新镜头
    shots = storyboard_data.get("shots", [])
    shot_index = None
    for i, shot in enumerate(shots):
        if shot.get("sequence") == sequence:
            shot_index = i
            break

    if shot_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Shot {sequence} not found")

    # 更新字段
    update_dict = update.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            if isinstance(value, dict):
                shots[shot_index][key] = {**shots[shot_index].get(key, {}), **value}
            else:
                shots[shot_index][key] = value

    # 保存
    chapter.metadata["storyboard"]["shots"] = shots
    await chapter.save()

    return shots[shot_index]


@router.delete("/chapters/{chapter_id}/shots/{sequence}")
async def delete_shot(
    chapter_id: UUID,
    sequence: int,
    current_user: UserModel = Depends(get_current_user),
):
    """删除单个分镜。"""
    chapter = await _verify_chapter_access(chapter_id, current_user)

    storyboard_data = chapter.metadata.get("storyboard")
    if not storyboard_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyboard not found")

    shots = storyboard_data.get("shots", [])
    new_shots = [s for s in shots if s.get("sequence") != sequence]

    if len(new_shots) == len(shots):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Shot {sequence} not found")

    # 重新编号
    for i, shot in enumerate(new_shots, start=1):
        shot["sequence"] = i

    total_duration = sum(s.get("technical", {}).get("duration", 0) for s in new_shots)

    chapter.metadata["storyboard"]["shots"] = new_shots
    chapter.metadata["storyboard"]["total_duration"] = total_duration
    chapter.scene_count = len(new_shots)
    await chapter.save()

    return {"message": "Shot deleted", "shot_count": len(new_shots)}


@router.post("/chapters/{chapter_id}/shots", response_model=dict)
async def add_shot(
    chapter_id: UUID,
    shot: dict,
    after_sequence: int | None = None,
    current_user: UserModel = Depends(get_current_user),
):
    """添加新分镜。"""
    chapter = await _verify_chapter_access(chapter_id, current_user)

    storyboard_data = chapter.metadata.get("storyboard")
    if not storyboard_data:
        storyboard_data = {"shots": [], "total_duration": 0}
        chapter.metadata["storyboard"] = storyboard_data

    shots = storyboard_data.get("shots", [])

    insert_index = len(shots) if after_sequence is None else after_sequence
    shot["sequence"] = insert_index + 1

    shots.insert(insert_index, shot)

    for i, s in enumerate(shots, start=1):
        s["sequence"] = i

    total_duration = sum(s.get("technical", {}).get("duration", 0) for s in shots)

    chapter.metadata["storyboard"]["shots"] = shots
    chapter.metadata["storyboard"]["total_duration"] = total_duration
    chapter.scene_count = len(shots)
    await chapter.save()

    return shot


@router.get("/chapters/{chapter_id}/prompts", response_model=StoryboardPromptsDTO)
async def get_storyboard_prompts(
    chapter_id: UUID,
    platform: str = "vidu",
    current_user: UserModel = Depends(get_current_user),
):
    """获取分镜的视频生成提示词。

    仅支持 vidu 和 doubao 平台。
    如果 shot 中已有预生成的 platform_prompt，则直接使用；否则实时构建。
    """
    # 验证平台
    if platform not in SUPPORTED_VIDEO_PLATFORMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的平台: {platform}，仅支持: {SUPPORTED_VIDEO_PLATFORMS}",
        )

    chapter = await _verify_chapter_access(chapter_id, current_user)

    storyboard_data = chapter.metadata.get("storyboard")
    if not storyboard_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storyboard not found")

    prompts = []
    for shot_data in storyboard_data.get("shots", []):
        try:
            shot = Shot.model_validate(shot_data)

            # 优先使用预生成的 platform_prompt（已包含 {ref:id} 占位符）
            if shot.platform_prompt:
                prompt = shot.platform_prompt
            else:
                # 回退：实时构建（但不包含资产引用）
                settings_obj = get_settings()
                service = create_storyboard_service(
                    api_key=settings_obj.llm.api_key,
                    base_url=settings_obj.llm.base_url,
                    model_name=settings_obj.llm.model_name,
                )
                prompt = service.build_platform_prompt(shot=shot, platform=platform)

            negative_prompt = shot.build_negative_prompt()

            prompts.append(
                ShotPromptDTO(
                    sequence=shot.sequence,
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    platform=platform,
                )
            )
        except Exception as e:
            logger.warning(f"Failed to build prompt for shot {shot_data.get('sequence')}: {e}")

    return StoryboardPromptsDTO(
        chapter_id=chapter_id,
        platform=platform,
        prompts=prompts,
    )
