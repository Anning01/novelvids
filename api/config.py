
from utils.messages import localized_message
import re
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, SecretStr, field_validator

from auth.deps import AuthContext, get_auth_context, require_roles, require_super_admin
from config import settings
from controllers.config import ai_model_config_controller, general_config_controller
from models.config import AiModelConfig
from services.studio_platform import SYNC_SCOPE, platform_connection_status, sync_platform_models, platform_account
from schemas.config import (
    AiModelConfigCreate,
    AiModelConfigOut,
    AiModelConfigPatch,
    AiModelConfigUpdate,
    GeneralConfigOut,
    GeneralConfigUpdate,
    LocaleOut,
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
from schemas.platform_billing import PlatformAccountOut

router = APIRouter()

# 模型能力/枚举清单不含密钥，登录用户（含创作者/查看者）可读，供工作台使用
_LOGGED_IN = Depends(get_auth_context)
# 设置类接口（模型配置 CRUD 与通用配置）仅团队管理员与超管可访问
_ADMIN = Depends(require_roles("admin"))


def _check_config_ownership(instance: AiModelConfig, ctx: AuthContext) -> None:
    """团队管理员只能修改本团队自定义配置；官方配置对其只读（404 不泄露）。"""
    if instance.scope == SYNC_SCOPE:
        raise HTTPException(409, localized_message("请通过平台同步管理此模型"))
    if ctx.user is None or ctx.is_super_admin:
        return
    if instance.team_id is None or instance.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail=localized_message('配置不存在或无权操作'))


def _check_config_read_access(instance: AiModelConfig, ctx: AuthContext) -> None:
    """平台级配置仅超管可见；团队管理员只可读本团队自定义配置。"""
    if ctx.user is None or ctx.is_super_admin:
        return
    if instance.team_id != ctx.team_id:
        raise HTTPException(status_code=404, detail=localized_message('配置不存在或无权操作'))


def _mask_official_key(item: AiModelConfigOut, ctx: AuthContext) -> AiModelConfigOut:
    """平台级配置不向团队暴露（列表/详情均已隔离）；超管可看全量。保留掩码以防他处复用。"""
    if item.scope == SYNC_SCOPE or (ctx.user is not None and not ctx.is_super_admin and item.scope == "official"):
        item.api_key = None
    return item


class PlatformKeyInput(BaseModel):
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"nv_[A-Za-z0-9_-]{1,125}", value.get_secret_value()):
            raise ValueError("Invalid platform API Key")
        return value


async def require_studio_owner(ctx: AuthContext = Depends(require_super_admin)) -> None:
    if settings.DEPLOYMENT_ROLE != "studio":
        raise HTTPException(404)
    if not ctx.is_super_admin:
        raise HTTPException(403, localized_message("仅超级管理员可执行此操作"))


_STUDIO_OWNER = Depends(require_studio_owner)


@router.get("/studio-platform", dependencies=[_STUDIO_OWNER])
async def get_studio_platform(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await platform_connection_status())


@router.get("/studio-platform/account", dependencies=[_STUDIO_OWNER], response_model=ResponseSchema[PlatformAccountOut])
async def get_platform_account(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await platform_account())


@router.put("/studio-platform", dependencies=[_STUDIO_OWNER])
async def set_studio_platform(payload: PlatformKeyInput, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await sync_platform_models(payload.api_key.get_secret_value()))


@router.post("/studio-platform/sync", dependencies=[_STUDIO_OWNER])
async def sync_studio_platform(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return ResponseSchema(data=await sync_platform_models())


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
    # 开放平台模型归属平台，侧边栏选中的团队只影响用量等团队页面。
    team_id = None if settings.DEPLOYMENT_ROLE == "platform" else ctx.team_id
    instance = await ai_model_config_controller.create(
        config,
        team_id=team_id,
        scope="team" if team_id else "official",
    )
    return ResponseSchema(data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx))


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
    for item in result["items"]:
        _mask_official_key(item, ctx)
    return ResponseSchema(data=result)


@router.get("/locale", response_model=ResponseSchema[LocaleOut])
async def get_locale():
    """Public display preference only; never expose the admin configuration."""
    from services.language import configured_language
    return ResponseSchema(data=LocaleOut(locale=await configured_language()))


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
async def update_general_config(config: GeneralConfigUpdate, ctx: AuthContext = _ADMIN):
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
        raise HTTPException(status_code=403, detail=localized_message('超级管理员无团队配置模式'))
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
        raise HTTPException(status_code=403, detail=localized_message('超级管理员无团队配置模式'))
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
    return ResponseSchema(data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx))


@router.patch("/{config_id}", summary="局部更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def patch_config(config_id: int, config: AiModelConfigPatch, ctx: AuthContext = _ADMIN):
    instance = await ai_model_config_controller.get(config_id)
    if instance.scope == SYNC_SCOPE and config.model_fields_set == {"pricing"}:
        await require_studio_owner(ctx)
    else:
        _check_config_ownership(instance, ctx)
    instance = await ai_model_config_controller.patch(config_id, config)
    return ResponseSchema(data=_mask_official_key(AiModelConfigOut.model_validate(instance), ctx))


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
