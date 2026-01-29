"""章节相关的 API 端点。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from novelvids.api.exceptions import (
    BadRequestException,
    NotFoundException,
    PermissionDeniedException,
)

from novelvids.api.dependencies import (
    get_current_user_id,
    get_chapter_repository,
    get_novel_repository,
)
from novelvids.application.dto import (
    ChapterCreateDTO,
    ChapterDetailDTO,
    ChapterResponseDTO,
    PaginatedResponseDTO,
)
from novelvids.infrastructure.database.repositories import (
    TortoiseChapterRepository,
    TortoiseNovelRepository,
)

router = APIRouter(prefix="/chapters", tags=["章节"])


@router.get("", response_model=PaginatedResponseDTO)
async def list_chapters(
    novel_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """列出指定小说的所有章节。"""
    novel = await novel_repo.get_by_id(novel_id)
    if novel is None:
        raise NotFoundException(code="NOVEL_NOT_FOUND", message="Novel not found")
    if novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    skip = (page - 1) * page_size
    chapters = await chapter_repo.get_all(
        skip=skip, limit=page_size, filters={"novel_id": novel_id}
    )
    total = await chapter_repo.count(filters={"novel_id": novel_id})
    total_pages = (total + page_size - 1) // page_size

    return PaginatedResponseDTO(
        items=[ChapterResponseDTO.model_validate(c) for c in chapters],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=ChapterResponseDTO, status_code=status.HTTP_201_CREATED)
async def create_chapter(
    novel_id: UUID,
    data: ChapterCreateDTO,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
):
    """手动创建章节。"""
    novel = await novel_repo.get_by_id(novel_id)
    if novel is None:
        raise NotFoundException(code="NOVEL_NOT_FOUND", message="Novel not found")
    if novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    # Auto-assign number if not provided
    number = data.number
    if number is None:
        max_number = await chapter_repo.get_max_number(novel_id)
        number = (max_number or 0) + 1

    chapter = await chapter_repo.create(
        novel_id=novel_id,
        title=data.title,
        content=data.content or "",
        number=number,
        status="pending",
        workflow_status="pending",
    )

    # Update novel chapter count
    await novel_repo.update(novel_id, {
        "total_chapters": novel.total_chapters + 1
    })

    return ChapterResponseDTO.model_validate(chapter)


@router.get("/{chapter_id}", response_model=ChapterDetailDTO)
async def get_chapter(
    chapter_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
):
    """根据 ID 获取特定章节。"""
    chapter = await chapter_repo.get_by_id(chapter_id)
    if chapter is None:
        raise NotFoundException(code="CHAPTER_NOT_FOUND", message="Chapter not found")

    novel = await novel_repo.get_by_id(chapter.novel_id)
    if novel is None or novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    return ChapterDetailDTO.model_validate(chapter)


@router.put("/{chapter_id}", response_model=ChapterResponseDTO)
async def update_chapter(
    chapter_id: UUID,
    data: dict,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
):
    """更新章节。"""
    chapter = await chapter_repo.get_by_id(chapter_id)
    if chapter is None:
        raise NotFoundException(code="CHAPTER_NOT_FOUND", message="Chapter not found")

    novel = await novel_repo.get_by_id(chapter.novel_id)
    if novel is None or novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    allowed_fields = {"title", "content", "number"}
    update_data = {k: v for k, v in data.items() if k in allowed_fields}
    
    if not update_data:
        raise BadRequestException(
            code="INVALID_UPDATE_DATA",
            message="No valid update fields provided"
        )

    updated = await chapter_repo.update(chapter_id, update_data)
    return ChapterResponseDTO.model_validate(updated)


@router.delete("/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter(
    chapter_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
):
    """删除章节。"""
    chapter = await chapter_repo.get_by_id(chapter_id)
    if chapter is None:
        raise NotFoundException(code="CHAPTER_NOT_FOUND", message="Chapter not found")

    novel = await novel_repo.get_by_id(chapter.novel_id)
    if novel is None or novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    await chapter_repo.delete(chapter_id)
from tortoise.transactions import in_transaction

@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_chapters(
    chapter_updates: list[dict],
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
):
    """批量重新排序章节。"""
    if not chapter_updates:
        return

    # 验证所有章节属于同一用户和同一小说
    first_update = chapter_updates[0]
    first_chapter = await chapter_repo.get_by_id(first_update["id"])
    if not first_chapter:
        raise NotFoundException(code="CHAPTER_NOT_FOUND", message="Chapter not found")
    
    novel_id = first_chapter.novel_id
    novel = await novel_repo.get_by_id(novel_id)
    if not novel or novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    # 验证所有ID都在该小说下
    update_ids = {UUID(u["id"]) for u in chapter_updates}
    existing_count = await chapter_repo.count(filters={"novel_id": novel_id, "id__in": list(update_ids)})
    if existing_count != len(update_ids):
        raise BadRequestException(code="INVALID_CHAPTERS", message="All chapters must belong to the same novel")

    async with in_transaction():
        # 1. 临时移动到大偏移量以避免冲突
        TEMP_OFFSET = 1000000
        for update in chapter_updates:
            chapter_id = UUID(update["id"])
            # 先更新到一个不冲突的临时位置
            temp_number = update["number"] + TEMP_OFFSET
            await chapter_repo.update(chapter_id, {"number": temp_number})

        # 2. 更新到最终位置
        for update in chapter_updates:
            chapter_id = UUID(update["id"])
            await chapter_repo.update(chapter_id, {"number": update["number"]})


from pydantic import BaseModel

class WorkflowStatusUpdateDTO(BaseModel):
    """工作流状态更新请求。"""
    workflow_status: str


@router.patch("/{chapter_id}/workflow-status", response_model=ChapterResponseDTO)
async def update_chapter_workflow_status(
    chapter_id: UUID,
    data: WorkflowStatusUpdateDTO,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    chapter_repo: Annotated[TortoiseChapterRepository, Depends(get_chapter_repository)],
    novel_repo: Annotated[TortoiseNovelRepository, Depends(get_novel_repository)],
):
    """更新章节工作流状态。"""
    from novelvids.infrastructure.database.models import ChapterWorkflowStatus

    chapter = await chapter_repo.get_by_id(chapter_id)
    if chapter is None:
        raise NotFoundException(code="CHAPTER_NOT_FOUND", message="Chapter not found")

    novel = await novel_repo.get_by_id(chapter.novel_id)
    if novel is None or novel.user_id != user_id:
        raise PermissionDeniedException(code="PERMISSION_DENIED", message="Access denied")

    # Validate status value
    valid_statuses = [s.value for s in ChapterWorkflowStatus]
    if data.workflow_status not in valid_statuses:
        raise BadRequestException(
            code="INVALID_WORKFLOW_STATUS",
            message=f"Invalid workflow status. Must be one of: {valid_statuses}"
        )

    # Check transition is valid
    current_status = ChapterWorkflowStatus(chapter.workflow_status)
    target_status = ChapterWorkflowStatus(data.workflow_status)

    if not current_status.can_transition_to(target_status):
        raise BadRequestException(
            code="INVALID_STATUS_TRANSITION",
            message=f"Cannot transition from {current_status.value} to {target_status.value}"
        )

    updated = await chapter_repo.update(chapter_id, {"workflow_status": data.workflow_status})
    return ChapterResponseDTO.model_validate(updated)
