from fastapi import APIRouter, Depends

from controllers.config import ai_model_config_controller
from schemas.config import (
    AiModelConfigCreate,
    AiModelConfigOut,
    AiModelConfigPatch,
    AiModelConfigUpdate,
)
from utils.enums import (
    AssetTypeEnum,
    AiTaskTypeEnum,
    ImageSourceEnum,
    TaskStatusEnum,
    VideoModelTypeEnum,
    WorkflowStatus,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


def _serialize_enum(enum_cls) -> list[dict]:
    """将 NicknameIntEnum 序列化为 [{value, label, name}]。"""
    return [
        {"value": m.value, "label": m.nickname, "name": m.name}
        for m in enum_cls
    ]


@router.get("/enums/all", summary="获取所有枚举配置", response_model=ResponseSchema)
async def get_all_enums():
    """返回前端需要的所有枚举定义，避免前端维护重复的枚举。"""
    return ResponseSchema(data={
        "task_status": _serialize_enum(TaskStatusEnum),
        "asset_type": _serialize_enum(AssetTypeEnum),
        "image_source": _serialize_enum(ImageSourceEnum),
        "workflow_status": _serialize_enum(WorkflowStatus),
        "ai_task_type": _serialize_enum(AiTaskTypeEnum),
        "video_model_type": _serialize_enum(VideoModelTypeEnum),
    })


@router.post("", summary="创建模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def create_config(config: AiModelConfigCreate):
    instance = await ai_model_config_controller.create(config)
    return ResponseSchema(data=instance)


@router.get(
    "", summary="获取模型配置列表", response_model=ResponseSchema[PaginationResponse[AiModelConfigOut]]
)
async def get_config_list(params: QueryParams = Depends(get_list_params)):
    result = await ai_model_config_controller.list(params, AiModelConfigOut)
    return ResponseSchema(data=result)


@router.get("/{config_id}", summary="获取模型配置详情", response_model=ResponseSchema[AiModelConfigOut])
async def get_config(config_id: int):
    instance = await ai_model_config_controller.get(config_id)
    return ResponseSchema(data=instance)


@router.put("/{config_id}", summary="全量更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def update_config(config_id: int, config: AiModelConfigUpdate):
    instance = await ai_model_config_controller.update(config_id, config)
    return ResponseSchema(data=instance)


@router.patch("/{config_id}", summary="局部更新模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def patch_config(config_id: int, config: AiModelConfigPatch):
    instance = await ai_model_config_controller.patch(config_id, config)
    return ResponseSchema(data=instance)


@router.delete("/{config_id}", summary="删除模型配置", response_model=ResponseSchema)
async def delete_config(config_id: int):
    await ai_model_config_controller.remove(config_id)
    return ResponseSchema()


@router.post("/{config_id}/activate", summary="启用模型配置", response_model=ResponseSchema[AiModelConfigOut])
async def activate_config(config_id: int):
    instance = await ai_model_config_controller.activate(config_id)
    return ResponseSchema(data=instance)
