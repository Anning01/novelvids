from fastapi import APIRouter, Depends, BackgroundTasks, Query
from uuid import UUID

from auth.deps import (
    AuthContext,
    ensure_novel_access,
    get_auth_context,
    require_asset_access,
    require_chapter_access,
    require_roles,
)
from controllers.asset import asset_controller
from models.asset import Asset
from schemas.ai_task import AiTaskOut
from schemas.asset import (
    AssetBriefOut,
    AssetCreate,
    AssetGenerationRecordOut,
    AssetImageEditCreate,
    AssetMergeOut,
    AssetMergeRequest,
    AssetOut,
    AssetPatch,
    AssetReferencePromptOut,
    AssetReferencePromptPreview,
    AssetReferenceCreate,
    AssetUpdate,
    AssetWithVariantsOut,
)
from schemas.asset_variant import (
    AssetVariantChapterAssignment,
    AssetVariantCreate,
    AssetVariantOut,
    AssetVariantPatch,
)
from controllers.config import general_config_controller
from services.ai_task_executor import ai_task_executor
from services.reference.generator import build_sora_compatible_prompt
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

_EDITOR = Depends(require_roles("admin", "creator"))


@router.post("", summary="创建资产", response_model=ResponseSchema[AssetOut])
async def create_asset(
    asset: AssetCreate,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    await ensure_novel_access(asset.novel_id, ctx)
    assets = await asset_controller.create(asset)
    return ResponseSchema(data=assets)


@router.put("/{asset_id}", summary="全量修改资产", response_model=ResponseSchema[AssetOut])
async def update_asset(
    asset_id: int,
    asset: AssetUpdate,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    assets = await asset_controller.update(asset_id, asset)
    return ResponseSchema(data=assets)


@router.patch("/{asset_id}", summary="局部更新资产", response_model=ResponseSchema[AssetOut])
async def patch_asset(
    asset_id: int,
    asset: AssetPatch,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    assets = await asset_controller.patch(asset_id, asset)
    return ResponseSchema(data=assets)


@router.get(
    "", summary="获取资产列表", response_model=ResponseSchema[PaginationResponse[AssetBriefOut]]
)
async def get_asset_list(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = Depends(get_auth_context),
):
    base_query = None
    if ctx.team_id is not None:
        base_query = Asset.filter(novel__team_id=ctx.team_id)
    assets = await asset_controller.list(params, AssetBriefOut, base_query=base_query)
    return ResponseSchema(data=assets)


@router.post(
    "/reference-prompt/preview",
    summary="预览资产最终生图提示词",
    response_model=ResponseSchema[AssetReferencePromptOut],
)
async def preview_asset_reference_prompt(
    payload: AssetReferencePromptPreview,
    _: AuthContext = _EDITOR,
):
    prompt_language = await general_config_controller.get_prompt_language()
    data = payload.model_dump()
    data["type"] = payload.asset_type.name
    return ResponseSchema(data={
        "prompt": build_sora_compatible_prompt(data, prompt_language),
        "prompt_language": prompt_language,
    })


@router.post(
    "/merge",
    summary="增量合并两个重复资产",
    response_model=ResponseSchema[AssetMergeOut],
)
async def merge_assets(
    payload: AssetMergeRequest,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    for asset_id in (payload.source_asset_id, payload.target_asset_id):
        await require_asset_access(asset_id, ctx)
    result = await asset_controller.merge(
        payload.source_asset_id,
        payload.target_asset_id,
    )
    result["asset"] = AssetWithVariantsOut.model_validate(result["asset"])
    return ResponseSchema(
        data=result
    )


@router.get(
    "/active-generations",
    summary="查询项目内进行中的参考图生成任务",
    response_model=ResponseSchema[list[dict]],
)
async def active_asset_generations(
    novel_id: int = Query(..., description="项目 ID"),
    ctx: AuthContext = Depends(get_auth_context),
):
    await ensure_novel_access(novel_id, ctx)
    return ResponseSchema(data=await asset_controller.active_generations(novel_id))


@router.get(
    "/{asset_id}", summary="获取资产详情", response_model=ResponseSchema[AssetWithVariantsOut]
)
async def get_asset(
    asset_id: int,
    _: AuthContext = Depends(require_asset_access),
):
    asset = await asset_controller.get_with_variants(asset_id)
    return ResponseSchema(data=asset)


@router.get(
    "/{asset_id}/generation-history",
    summary="获取资产生图记录",
    response_model=ResponseSchema[list[AssetGenerationRecordOut]],
)
async def get_asset_generation_history(
    asset_id: int,
    _: AuthContext = Depends(require_asset_access),
):
    return ResponseSchema(data=await asset_controller.generation_history(asset_id))


@router.post(
    "/{asset_id}/generation-history/edit",
    summary="保存资产图片标注并创建生成记录",
    response_model=ResponseSchema[AssetOut],
)
async def record_asset_image_edit(
    asset_id: int,
    payload: AssetImageEditCreate,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    return ResponseSchema(data=await asset_controller.record_image_edit(asset_id, payload))


@router.post(
    "/{asset_id}/generation-history/{task_id}/restore",
    summary="将历史生图结果设为当前图片",
    response_model=ResponseSchema[AssetOut],
)
async def restore_asset_generation(
    asset_id: int,
    task_id: UUID,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    return ResponseSchema(data=await asset_controller.restore_generation(asset_id, task_id))


@router.get(
    "/{asset_id}/variants",
    summary="获取资产的全部视觉形态",
    response_model=ResponseSchema[list[AssetVariantOut]],
)
async def get_asset_variants(
    asset_id: int,
    _: AuthContext = Depends(require_asset_access),
):
    variants = await asset_controller.list_variants(asset_id)
    return ResponseSchema(
        data=[AssetVariantOut.model_validate(variant) for variant in variants]
    )


@router.post(
    "/{asset_id}/variants",
    summary="新增人物变装、场景升级或道具形态",
    response_model=ResponseSchema[AssetVariantOut],
)
async def create_asset_variant(
    asset_id: int,
    variant: AssetVariantCreate,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
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
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    return ResponseSchema(
        data=await asset_controller.patch_variant(asset_id, variant_id, variant)
    )


@router.post(
    "/{asset_id}/variants/{variant_id}/chapter",
    summary="将衍生形态设为指定集唯一使用状态",
    response_model=ResponseSchema[list[AssetVariantOut]],
)
async def assign_asset_variant_to_chapter(
    asset_id: int,
    variant_id: int,
    payload: AssetVariantChapterAssignment,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    variants = await asset_controller.assign_variant_to_chapter(
        asset_id,
        variant_id,
        payload.chapter_number,
    )
    return ResponseSchema(
        data=[AssetVariantOut.model_validate(variant) for variant in variants]
    )


@router.delete(
    "/{asset_id}/variants/{variant_id}",
    summary="删除资产视觉形态",
    response_model=ResponseSchema,
)
async def delete_asset_variant(
    asset_id: int,
    variant_id: int,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    await asset_controller.remove_variant(asset_id, variant_id)
    return ResponseSchema()


@router.delete(
    "/{asset_id}", summary="删除一个资产", response_model=ResponseSchema
)
async def delete_asset(
    asset_id: int,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = _EDITOR,
):
    await asset_controller.remove(asset_id)
    return ResponseSchema()


@router.post(
    "/{asset_id}/chapters/{chapter_id}",
    summary="将项目资产复用到指定章节",
    response_model=ResponseSchema[AssetWithVariantsOut],
)
async def reuse_asset_in_chapter(
    asset_id: int,
    chapter_id: int,
    _: AuthContext = Depends(require_asset_access),
    __: AuthContext = Depends(require_chapter_access),
    ___: AuthContext = _EDITOR,
):
    return ResponseSchema(
        data=await asset_controller.reuse_in_chapter(asset_id, chapter_id)
    )


@router.get("/reference/{asset_id}", summary="生成资产参考图", response_model=ResponseSchema[AiTaskOut])
async def asset_reference(
    asset_id: int,
    bg: BackgroundTasks,
    variant_id: int | None = Query(default=None),
    ctx: AuthContext = Depends(require_asset_access),
    _: AuthContext = _EDITOR,
):
    task = await asset_controller.reference(
        asset_id,
        variant_id,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)


@router.post(
    "/reference/{asset_id}",
    summary="使用可选参考图片生成资产设定图",
    response_model=ResponseSchema[AiTaskOut],
)
async def asset_reference_with_images(
    asset_id: int,
    payload: AssetReferenceCreate,
    bg: BackgroundTasks,
    ctx: AuthContext = Depends(require_asset_access),
    _: AuthContext = _EDITOR,
):
    task = await asset_controller.reference(
        asset_id,
        payload.variant_id,
        reference_images=payload.reference_images,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    bg.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=task)
