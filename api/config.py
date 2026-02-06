from fastapi import APIRouter, Depends

from controllers.config import ai_model_config_controller
from schemas.config import (
    AiModelConfigCreate,
    AiModelConfigOut,
    AiModelConfigPatch,
    AiModelConfigUpdate,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


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
