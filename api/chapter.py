from fastapi import APIRouter, BackgroundTasks, Depends

from controllers.chapter import chapter_controller
from schemas.ai_task import AiTaskOut
from schemas.chapter import ChapterBriefOut, ChapterCreate, ChapterUpdate, ChapterPatch, ChapterOut
from services.ai_task_executor import ai_task_executor
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.post("", summary="创建章节", response_model=ResponseSchema[ChapterOut])
async def create_chapter(chapter: ChapterCreate):
    chapters = await chapter_controller.create(chapter)
    return ResponseSchema(data=chapters)


@router.put("/{chapter_id}", summary="全量修改章节", response_model=ResponseSchema[ChapterOut])
async def update_chapter(chapter_id: int, chapter: ChapterUpdate):
    chapters = await chapter_controller.update(chapter_id, chapter)
    return ResponseSchema(data=chapters)


@router.patch("/{chapter_id}", summary="局部更新章节", response_model=ResponseSchema[ChapterOut])
async def patch_chapter(chapter_id: int, chapter: ChapterPatch):
    chapters = await chapter_controller.patch(chapter_id, chapter)
    return ResponseSchema(data=chapters)


@router.get(
    "", summary="获取章节列表", response_model=ResponseSchema[PaginationResponse[ChapterBriefOut]]
)
async def get_chapter_list(params: QueryParams = Depends(get_list_params)):
    chapters = await chapter_controller.list(params, ChapterBriefOut)
    return ResponseSchema(data=chapters)


@router.get(
    "/{chapter_id}", summary="获取章节详情", response_model=ResponseSchema[ChapterOut]
)
async def get_chapter(chapter_id: int):
    chapter = await chapter_controller.get(chapter_id)
    return ResponseSchema(data=chapter)


@router.delete(
    "/{chapter_id}", summary="删除一个章节", response_model=ResponseSchema
)
async def delete_chapter(chapter_id: int):
    await chapter_controller.remove(chapter_id)
    return ResponseSchema()

@router.post("/extract/{chapter_id}", summary="连通分量+增量式状态机提取", response_model=ResponseSchema[AiTaskOut])
async def extract_chapter(chapter_id: int, bg: BackgroundTasks):
    task = await chapter_controller.extract(chapter_id)
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)