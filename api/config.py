from fastapi import APIRouter, Depends, HTTPException

from auth.deps import AuthContext, get_auth_context, require_roles
from controllers.config import ai_model_config_controller, general_config_controller
from models.config import AiModelConfig
from schemas.config import (
    AiModelConfigCreate,
    AiModelConfigOut,
    AiModelConfigPatch,
    AiModelConfigUpdate,
    GeneralConfigOut,
    GeneralConfigUpdate,
    ImageGenerationModelOut,
    ModelConfigSourceOut,
    ModelConfigSourceUpdate,
    VideoGenerationModelOut,
)
from tortoise.expressions import Q
from utils.enums import (
    AssetTypeEnum,
    AiTaskTypeEnum,
    ImageSourceEnum,
    TaskStatusEnum,
    VideoGenerationModelTypeEnum,
    ImageModelTypeEnum,
    WorkflowStatus,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

# 模型能力/枚举清单不含密钥，登录用户（含创作者/查看者）可读，供工作台使用
_LOGGED_IN = Depends(get_auth_context)
# 设置类接口（模型配置 CRUD 与通用配置）仅团队管理员与超管可访问
_ADMIN = Depends(require_roles("admin"))


def _check_config_ownership(instance: AiModelConfig, ctx: AuthContext) -> None:
    """团队管理员只能修改本团队自定义配置；官方配置对其只读（404 不泄露）。"""
    if ctx.user is None or ctx.is_super_admin:
        return
    if instance.team_id is None or instance.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail="配置不存在或无权操作")


def _check_config_read_access(instance: AiModelConfig, ctx: AuthContext) -> None:
    """平台级配置仅超管可见；团队管理员只可读本团队自定义配置。"""
    if ctx.user is None or ctx.is_super_admin:
        return
    if instance.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail="配置不存在或无权操作")


def _mask_official_key(item: AiModelConfigOut, ctx: AuthContext) -> AiModelConfigOut:
    """平台级配置不向团队暴露（列表/详情均已隔离）；超管可看全量。保留掩码以防他处复用。"""
    if ctx.user is not None and not ctx.is_super_admin and item.scope == "official":
        item.api_key = None
    return item


def _serialize_enum(enum_cls) -> list[dict]:
    """将 NicknameIntEnum 序列化为 [{value, label, name}]。"""
    return [
        {"value": m.value, "label": m.nickname, "name": m.name}
        for m in enum_cls
    ]


@router.get("/enums/all", summary="获取所有枚举配置", response_model=ResponseSchema)
async def get_all_enums(_: AuthContext = _LOGGED_IN):
    """返回前端需要的所有枚举定义，避免前端维护重复的枚举。"""
    return ResponseSchema(data={
        "task_status": _serialize_enum(TaskStatusEnum),
        "asset_type": _serialize_enum(AssetTypeEnum),
        "image_source": _serialize_enum(ImageSourceEnum),
        "workflow_status": _serialize_enum(WorkflowStatus),
        "ai_task_type": _serialize_enum(AiTaskTypeEnum),
        "video_model_type": _serialize_enum(VideoGenerationModelTypeEnum),
        "image_model_type": _serialize_enum(ImageModelTypeEnum),
    })


@router.get(
    "/image-generation/models",
    summary="获取当前可用的生图模型及参数能力",
    response_model=ResponseSchema[list[ImageGenerationModelOut]],
)
async def get_image_generation_models(ctx: AuthContext = _LOGGED_IN):
    return ResponseSchema(
        data=await ai_model_config_controller.list_active_image_models(ctx.team_id)
    )


@router.get(
    "/video-generation/models",
    summary="获取当前可用的视频模型及参数能力",
    response_model=ResponseSchema[list[VideoGenerationModelOut]],
)
async def get_video_generation_models(ctx: AuthContext = _LOGGED_IN):
    return ResponseSchema(
        data=await ai_model_config_controller.list_active_video_models(ctx.team_id)
    )


@router.get(
    "/generation/capabilities",
    summary="获取各模型类型的清晰度/分辨率档位",
    response_model=ResponseSchema,
)
async def get_generation_capabilities(_: AuthContext = _LOGGED_IN):
    return ResponseSchema(data=await ai_model_config_controller.list_generation_capabilities())


@router.get(
    "/visual-styles",
    summary="获取视觉风格清单（生图/生视频提示词注册表）",
    response_model=ResponseSchema,
)
async def get_visual_styles(_: AuthContext = _LOGGED_IN):
    return ResponseSchema(data=await ai_model_config_controller.list_visual_styles())


@router.post("", summary="创建模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def create_config(config: AiModelConfigCreate, ctx: AuthContext = _ADMIN):
    # 超管（team_id=None）创建官方配置；团队管理员创建本团队自定义配置
    instance = await ai_model_config_controller.create(
        config,
        team_id=ctx.team_id,
        scope="team" if ctx.team_id else "official",
    )
    return ResponseSchema(data=instance)


@router.get(
    "", summary="获取模型配置列表", response_model=ResponseSchema[PaginationResponse[AiModelConfigOut]]
)
async def get_config_list(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = _ADMIN,
):
    base_query = None
    if ctx.user is not None and not ctx.is_super_admin:
        # 团队管理员仅可见本团队自定义配置；平台级配置只有超管可见
        base_query = AiModelConfig.filter(team_id=ctx.team_id)
    result = await ai_model_config_controller.list(
        params, AiModelConfigOut, base_query=base_query
    )
    if ctx.user is not None and not ctx.is_super_admin:
        for item in result["items"]:
            _mask_official_key(item, ctx)
    return ResponseSchema(data=result)


@router.get(
    "/general",
    summary="获取通用配置",
    response_model=ResponseSchema[GeneralConfigOut],
)
async def get_general_config(_: AuthContext = _ADMIN):
    instance = await general_config_controller.get()
    return ResponseSchema(data=instance)


@router.put(
    "/general",
    summary="更新通用配置",
    response_model=ResponseSchema[GeneralConfigOut],
)
async def update_general_config(config: GeneralConfigUpdate, _: AuthContext = _ADMIN):
    instance = await general_config_controller.update(config)
    return ResponseSchema(data=instance)


# ---- 团队模型配置来源模式（团队管理员） ----


@router.get(
    "/team/model-source",
    summary="获取团队模型配置来源模式",
    response_model=ResponseSchema[ModelConfigSourceOut],
)
async def get_model_source(ctx: AuthContext = _ADMIN):
    if ctx.user is None:
        return ResponseSchema(data={"source": "official"})
    if ctx.is_super_admin:
        raise HTTPException(status_code=403, detail="超级管理员无团队配置模式")
    return ResponseSchema(
        data={
            "source": await ai_model_config_controller.get_model_config_source(
                ctx.team_id
            )
        }
    )


@router.put(
    "/team/model-source",
    summary="切换团队模型配置来源（official/custom）",
    response_model=ResponseSchema[ModelConfigSourceOut],
)
async def set_model_source(payload: ModelConfigSourceUpdate, ctx: AuthContext = _ADMIN):
    if ctx.user is None:
        return ResponseSchema(data={"source": payload.source})
    if ctx.is_super_admin:
        raise HTTPException(status_code=403, detail="超级管理员无团队配置模式")
    source = await ai_model_config_controller.set_model_config_source(
        ctx.team_id, payload.source
    )
    return ResponseSchema(data={"source": source})


@router.get("/{config_id}", summary="获取模型配置详情", response_model=ResponseSchema[AiModelConfigOut])
async def get_config(config_id: int, ctx: AuthContext = _ADMIN):
    instance = await ai_model_config_controller.get(config_id)
    _check_config_read_access(instance, ctx)
    return ResponseSchema(
        data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx)
    )


@router.put("/{config_id}", summary="全量更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def update_config(config_id: int, config: AiModelConfigUpdate, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.update(config_id, config)
    return ResponseSchema(data=instance)


@router.patch("/{config_id}", summary="局部更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def patch_config(config_id: int, config: AiModelConfigPatch, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.patch(config_id, config)
    return ResponseSchema(data=instance)


@router.delete("/{config_id}", summary="删除模型配置", response_model=ResponseSchema)
async def delete_config(config_id: int, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    await ai_model_config_controller.remove(config_id)
    return ResponseSchema()


@router.post("/{config_id}/activate", summary="启用模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def activate_config(config_id: int, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.activate(config_id)
    return ResponseSchema(data=instance)


@router.post("/{config_id}/deactivate", summary="停用模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def deactivate_config(config_id: int, ctx: AuthContext = _ADMIN):
    _check_config_ownership(await ai_model_config_controller.get(config_id), ctx)
    instance = await ai_model_config_controller.deactivate(config_id)
    return ResponseSchema(data=instance)
