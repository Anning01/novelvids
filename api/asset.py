from fastapi import APIRouter, Depends, BackgroundTasks, Query

from controllers.asset import asset_controller
from schemas.ai_task import AiTaskOut
from schemas.asset import AssetBriefOut, AssetCreate, AssetUpdate, AssetPatch, AssetOut, AssetWithVariantsOut
from schemas.asset_variant import AssetVariantCreate, AssetVariantOut, AssetVariantPatch
from services.ai_task_executor import ai_task_executor
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.post("", summary="创建资产", response_model=ResponseSchema[AssetOut])
async def create_asset(asset: AssetCreate):
    assets = await asset_controller.create(asset)
    return ResponseSchema(data=assets)


@router.put("/{asset_id}", summary="全量修改资产", response_model=ResponseSchema[AssetOut])
async def update_asset(asset_id: int, asset: AssetUpdate):
    assets = await asset_controller.update(asset_id, asset)
    return ResponseSchema(data=assets)


@router.patch("/{asset_id}", summary="局部更新资产", response_model=ResponseSchema[AssetOut])
async def patch_asset(asset_id: int, asset: AssetPatch):
    assets = await asset_controller.patch(asset_id, asset)
    return ResponseSchema(data=assets)


@router.get(
    "", summary="获取资产列表", response_model=ResponseSchema[PaginationResponse[AssetBriefOut]]
)
async def get_asset_list(params: QueryParams = Depends(get_list_params)):
    assets = await asset_controller.list(params, AssetBriefOut)
    return ResponseSchema(data=assets)


@router.get(
    "/{asset_id}", summary="获取资产详情", response_model=ResponseSchema[AssetWithVariantsOut]
)
async def get_asset(asset_id: int):
    asset = await asset_controller.get_with_variants(asset_id)
    return ResponseSchema(data=asset)


@router.get(
    "/{asset_id}/variants",
    summary="获取资产的全部视觉形态",
    response_model=ResponseSchema[list[AssetVariantOut]],
)
async def get_asset_variants(asset_id: int):
    return ResponseSchema(data=await asset_controller.list_variants(asset_id))


@router.post(
    "/{asset_id}/variants",
    summary="新增人物变装、场景升级或道具形态",
    response_model=ResponseSchema[AssetVariantOut],
)
async def create_asset_variant(asset_id: int, variant: AssetVariantCreate):
    return ResponseSchema(data=await asset_controller.create_variant(asset_id, variant))


@router.patch(
    "/{asset_id}/variants/{variant_id}",
    summary="修改资产视觉形态",
    response_model=ResponseSchema[AssetVariantOut],
)
async def patch_asset_variant(
    asset_id: int,
    variant_id: int,
    variant: AssetVariantPatch,
):
    return ResponseSchema(
        data=await asset_controller.patch_variant(asset_id, variant_id, variant)
    )


@router.delete(
    "/{asset_id}/variants/{variant_id}",
    summary="删除资产视觉形态",
    response_model=ResponseSchema,
)
async def delete_asset_variant(asset_id: int, variant_id: int):
    await asset_controller.remove_variant(asset_id, variant_id)
    return ResponseSchema()


@router.delete(
    "/{asset_id}", summary="删除一个资产", response_model=ResponseSchema
)
async def delete_asset(asset_id: int):
    await asset_controller.remove(asset_id)
    return ResponseSchema()


@router.post(
    "/{asset_id}/chapters/{chapter_id}",
    summary="将项目资产复用到指定章节",
    response_model=ResponseSchema[AssetWithVariantsOut],
)
async def reuse_asset_in_chapter(asset_id: int, chapter_id: int):
    return ResponseSchema(
        data=await asset_controller.reuse_in_chapter(asset_id, chapter_id)
    )


@router.get("/reference/{asset_id}", summary="生成资产参考图", response_model=ResponseSchema[AiTaskOut])
async def asset_reference(
    asset_id: int,
    bg: BackgroundTasks,
    variant_id: int | None = Query(default=None),
):
    task = await asset_controller.reference(asset_id, variant_id)
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)
