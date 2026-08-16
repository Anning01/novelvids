from fastapi import APIRouter, BackgroundTasks, Depends

from auth.deps import (
    AuthContext,
    ensure_novel_access,
    get_auth_context,
    require_chapter_access,
    require_roles,
)
from controllers.chapter import chapter_controller
from models.chapter import Chapter
from schemas.ai_task import AiTaskOut
from schemas.chapter import ChapterBriefOut, ChapterCreate, ChapterUpdate, ChapterPatch, ChapterOut
from services.ai_task_executor import ai_task_executor
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

_EDITOR = Depends(require_roles("admin", "creator"))


@router.post("", summary="创建章节", response_model=ResponseSchema[ChapterOut])
async def create_chapter(
    chapter: ChapterCreate,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    await ensure_novel_access(chapter.novel_id, ctx)
    chapters = await chapter_controller.create(chapter)
    return ResponseSchema(data=chapters)


@router.put("/{chapter_id}", summary="全量修改章节", response_model=ResponseSchema[ChapterOut])
async def update_chapter(
    chapter_id: int,
    chapter: ChapterUpdate,
    _: AuthContext = Depends(require_chapter_access),
    __: AuthContext = _EDITOR,
):
    chapters = await chapter_controller.update(chapter_id, chapter)
    return ResponseSchema(data=chapters)


@router.patch("/{chapter_id}", summary="局部更新章节", response_model=ResponseSchema[ChapterOut])
async def patch_chapter(
    chapter_id: int,
    chapter: ChapterPatch,
    _: AuthContext = Depends(require_chapter_access),
    __: AuthContext = _EDITOR,
):
    chapters = await chapter_controller.patch(chapter_id, chapter)
    return ResponseSchema(data=chapters)


@router.get(
    "", summary="获取章节列表", response_model=ResponseSchema[PaginationResponse[ChapterBriefOut]]
)
async def get_chapter_list(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = Depends(get_auth_context),
):
    base_query = None
    if ctx.team_id is not None:
        base_query = Chapter.filter(novel__team_id=ctx.team_id)
    chapters = await chapter_controller.list(
        params, ChapterBriefOut, base_query=base_query
    )
    return ResponseSchema(data=chapters)


@router.get(
    "/{chapter_id}", summary="获取章节详情", response_model=ResponseSchema[ChapterOut]
)
async def get_chapter(
    chapter_id: int,
    _: AuthContext = Depends(require_chapter_access),
):
    chapter = await chapter_controller.get(chapter_id)
    return ResponseSchema(data=chapter)


@router.delete(
    "/{chapter_id}", summary="删除一个章节", response_model=ResponseSchema
)
async def delete_chapter(
    chapter_id: int,
    _: AuthContext = Depends(require_chapter_access),
    __: AuthContext = _EDITOR,
):
    await chapter_controller.remove(chapter_id)
    return ResponseSchema()


@router.get(
    "/extract/{chapter_id}/latest",
    summary="获取章节最近一次提取任务",
    response_model=ResponseSchema[AiTaskOut | None],
)
async def get_latest_extraction_task(
    chapter_id: int,
    _: AuthContext = Depends(require_chapter_access),
):
    task = await chapter_controller.latest_extraction_task(chapter_id)
    return ResponseSchema(data=task)


@router.post("/extract/{chapter_id}", summary="连通分量+增量式状态机提取", response_model=ResponseSchema[AiTaskOut])
async def extract_chapter(
    chapter_id: int,
    bg: BackgroundTasks,
    ctx: AuthContext = Depends(require_chapter_access),
    _: AuthContext = _EDITOR,
):
    task = await chapter_controller.extract(
        chapter_id,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)
