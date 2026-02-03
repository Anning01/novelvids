"""资产提取 API 端点。

提供分离式的资产提取（人物/场景/物品），支持：
- 单独或批量提取
- 后台任务执行
- 进度轮询
- 超时控制和重试
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from novelvids.api.dependencies import (
    get_chapter_repository,
    get_current_user_id,
    get_novel_repository,
)
from novelvids.application.services.extraction_task_service import (
    ExtractionTaskService,
    extraction_task_service,
)
from novelvids.core.config import settings
from novelvids.infrastructure.database.models import (
    ExtractionTaskModel,
    ExtractionTaskType,
    TaskStatus,
)
from novelvids.infrastructure.database.repositories import (
    TortoiseChapterRepository,
    TortoiseNovelRepository,
)

router = APIRouter(prefix="/extraction", tags=["资产提取"])


# ============== DTOs ==============


class ExtractionTaskCreateDTO(BaseModel):
    """创建提取任务的请求。"""

    chapter_id: UUID
    task_type: str = Field(description="提取类型: person, scene, item")
    timeout_seconds: int = Field(default=120, ge=30, le=600)
    max_retries: int = Field(default=3, ge=0, le=5)


class ExtractionTaskBatchDTO(BaseModel):
    """批量创建提取任务的请求。"""

    chapter_id: UUID
    task_types: list[str] = Field(
        default=["person", "scene", "item"],
        description="要提取的类型列表",
    )
    timeout_seconds: int = Field(default=120, ge=30, le=600)


class ExtractionTaskResponseDTO(BaseModel):
    """提取任务响应。"""

    id: UUID
    chapter_id: UUID
    task_type: str
    status: str
    progress: int
    message: str | None
    retry_count: int
    result: dict | None
    error: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None

    class Config:
        from_attributes = True


class ChapterExtractionStatusDTO(BaseModel):
    """章节提取状态汇总。"""

    chapter_id: UUID
    person: ExtractionTaskResponseDTO | None
    scene: ExtractionTaskResponseDTO | None
    item: ExtractionTaskResponseDTO | None
    overall_progress: int  # 0-100
    is_complete: bool


# ============== Helper Functions ==============


def get_extraction_service() -> ExtractionTaskService:
    """获取提取任务服务。"""
    return extraction_task_service


async def verify_chapter_access(
    chapter_id: UUID,
    user_id: UUID,
    chapter_repo: TortoiseChapterRepository,
    novel_repo: TortoiseNovelRepository,
) -> None:
    """验证用户是否有权访问该章节。"""
    chapter = await chapter_repo.get_by_id(chapter_id)
    if chapter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")

    novel = await novel_repo.get_by_id(chapter.novel_id)
    if novel is None or novel.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="拒绝访问")


def task_to_dto(task: ExtractionTaskModel) -> ExtractionTaskResponseDTO:
    """将任务模型转换为 DTO。"""
    return ExtractionTaskResponseDTO(
        id=task.id,
        chapter_id=task.chapter_id,
        task_type=task.task_type.value,
        status=task.status.value,
        progress=task.progress,
        message=task.message,
        retry_count=task.retry_count,
        result=task.result,
        error=task.error,
        created_at=task.created_at.isoformat() if task.created_at else "",
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


# ============== Endpoints ==============


@router.post("/tasks", response_model=ExtractionTaskResponseDTO, status_code=status.HTTP_202_ACCEPTED)
async def create_extraction_task(
    data: ExtractionTaskCreateDTO,
    background_tasks: BackgroundTasks,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    service: Annotated[ExtractionTaskService, Depends(get_extraction_service)],
):
    """创建单个提取任务。

    任务会在后台执行，返回任务 ID 供轮询进度。
    """
    # 验证权限
    await verify_chapter_access(data.chapter_id, user_id, chapter_repo, novel_repo)

    # 验证 LLM 配置
    if not settings.llm.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API 未配置，请联系管理员",
        )

    # 验证任务类型
    try:
        task_type = ExtractionTaskType(data.task_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的任务类型: {data.task_type}，必须是 person, scene, item 之一",
        )

    # 创建任务
    task = await service.create_task(
        chapter_id=data.chapter_id,
        task_type=task_type,
        timeout_seconds=data.timeout_seconds,
        max_retries=data.max_retries,
    )

    # 如果是新任务，添加到后台执行
    if task.status == TaskStatus.PENDING:
        background_tasks.add_task(service.execute_task, task.id)

    return task_to_dto(task)


@router.post("/tasks/batch", response_model=list[ExtractionTaskResponseDTO], status_code=status.HTTP_202_ACCEPTED)
async def create_extraction_tasks_batch(
    data: ExtractionTaskBatchDTO,
    background_tasks: BackgroundTasks,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    service: Annotated[ExtractionTaskService, Depends(get_extraction_service)],
):
    """批量创建提取任务。

    同时创建多个类型的提取任务。
    """
    # 验证权限
    await verify_chapter_access(data.chapter_id, user_id, chapter_repo, novel_repo)

    # 验证 LLM 配置
    if not settings.llm.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM API 未配置，请联系管理员",
        )

    tasks = []
    for type_str in data.task_types:
        try:
            task_type = ExtractionTaskType(type_str)
        except ValueError:
            continue  # 跳过无效类型

        task = await service.create_task(
            chapter_id=data.chapter_id,
            task_type=task_type,
            timeout_seconds=data.timeout_seconds,
        )

        # 如果是新任务，添加到后台执行
        if task.status == TaskStatus.PENDING:
            background_tasks.add_task(service.execute_task, task.id)

        tasks.append(task)

    return [task_to_dto(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=ExtractionTaskResponseDTO)
async def get_extraction_task(
    task_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    service: Annotated[ExtractionTaskService, Depends(get_extraction_service)],
):
    """获取任务详情。

    用于轮询任务进度。
    """
    task = await service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    # 验证权限
    await verify_chapter_access(task.chapter_id, user_id, chapter_repo, novel_repo)

    return task_to_dto(task)


@router.get("/chapters/{chapter_id}/status", response_model=ChapterExtractionStatusDTO)
async def get_chapter_extraction_status(
    chapter_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    service: Annotated[ExtractionTaskService, Depends(get_extraction_service)],
):
    """获取章节的提取状态汇总。

    返回所有类型的最新任务状态。
    """
    # 验证权限
    await verify_chapter_access(chapter_id, user_id, chapter_repo, novel_repo)

    tasks = await service.get_chapter_tasks(chapter_id)

    # 计算总体进度
    total_progress = 0
    completed_count = 0
    task_count = 0

    person_dto = None
    scene_dto = None
    item_dto = None

    if tasks["person"]:
        person_dto = task_to_dto(tasks["person"])
        total_progress += tasks["person"].progress
        task_count += 1
        if tasks["person"].status == TaskStatus.COMPLETED:
            completed_count += 1

    if tasks["scene"]:
        scene_dto = task_to_dto(tasks["scene"])
        total_progress += tasks["scene"].progress
        task_count += 1
        if tasks["scene"].status == TaskStatus.COMPLETED:
            completed_count += 1

    if tasks["item"]:
        item_dto = task_to_dto(tasks["item"])
        total_progress += tasks["item"].progress
        task_count += 1
        if tasks["item"].status == TaskStatus.COMPLETED:
            completed_count += 1

    overall_progress = total_progress // task_count if task_count > 0 else 0
    is_complete = completed_count == 3 and task_count == 3

    return ChapterExtractionStatusDTO(
        chapter_id=chapter_id,
        person=person_dto,
        scene=scene_dto,
        item=item_dto,
        overall_progress=overall_progress,
        is_complete=is_complete,
    )


@router.post("/tasks/{task_id}/retry", response_model=ExtractionTaskResponseDTO)
async def retry_extraction_task(
    task_id: UUID,
    background_tasks: BackgroundTasks,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    service: Annotated[ExtractionTaskService, Depends(get_extraction_service)],
):
    """重试失败的任务。"""
    task = await service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    # 验证权限
    await verify_chapter_access(task.chapter_id, user_id, chapter_repo, novel_repo)

    # 只能重试失败的任务
    if task.status != TaskStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能重试失败的任务",
        )

    # 创建新任务
    new_task = await service.create_task(
        chapter_id=task.chapter_id,
        task_type=task.task_type,
        timeout_seconds=task.timeout_seconds,
        max_retries=task.max_retries,
    )

    # 添加到后台执行
    if new_task.status == TaskStatus.PENDING:
        background_tasks.add_task(service.execute_task, new_task.id)

    return task_to_dto(new_task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_extraction_task(
    task_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    service: Annotated[ExtractionTaskService, Depends(get_extraction_service)],
):
    """取消任务（仅限待执行的任务）。"""
    task = await service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    # 验证权限
    await verify_chapter_access(task.chapter_id, user_id, chapter_repo, novel_repo)

    # 只能取消待执行的任务
    if task.status not in [TaskStatus.PENDING, TaskStatus.QUEUED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只能取消待执行的任务",
        )

    task.status = TaskStatus.CANCELLED
    task.message = "用户取消"
    await task.save()
