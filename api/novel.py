from fastapi import APIRouter, Depends

from controllers.novel import novel_controller
from schemas.novel import NovelBriefOut, NovelCreate, NovelUpdate, NovelPatch, NovelOut
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.post("", summary="创建小说/剧本", response_model=ResponseSchema[NovelOut])
async def create_novel(novel: NovelCreate):
    novels = await novel_controller.create(novel)
    return ResponseSchema(data=novels)


@router.put("/{novel_id}", summary="全量修改小说/剧本", response_model=ResponseSchema[NovelOut])
async def update_novel(novel_id: int, novel: NovelUpdate):
    novels = await novel_controller.update(novel_id, novel)
    return ResponseSchema(data=novels)


@router.patch("/{novel_id}", summary="局部更新小说/剧本", response_model=ResponseSchema[NovelOut])
async def patch_novel(novel_id: int, novel: NovelPatch):
    novels = await novel_controller.patch(novel_id, novel)
    return ResponseSchema(data=novels)


@router.get(
    "", summary="获取小说/剧本列表", response_model=ResponseSchema[PaginationResponse[NovelBriefOut]]
)
async def get_novel_list(params: QueryParams = Depends(get_list_params)):
    novels = await novel_controller.list(params, NovelBriefOut, search_fields=['name', 'author'])
    return ResponseSchema(data=novels)


@router.get(
    "/{novel_id}", summary="获取小说/剧本详情", response_model=ResponseSchema[NovelOut]
)
async def get_novel(novel_id: int):
    novel = await novel_controller.get(novel_id)
    return ResponseSchema(data=novel)


@router.delete(
    "/{novel_id}", summary="删除一个小说/剧本", response_model=ResponseSchema
)
async def delete_novel(novel_id: int):
    await novel_controller.remove(novel_id)
    return ResponseSchema()


@router.get("/{novel_id}/split", summary="使用nlp智能拆分章节", response_model=ResponseSchema[NovelOut])
async def split_novel(novel_id: int):
    novel = await novel_controller.split(novel_id)
    return ResponseSchema(data=novel)
