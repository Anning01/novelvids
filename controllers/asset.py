from typing import Any, Optional, Type

from fastapi import HTTPException
from pydantic import BaseModel
from tortoise.queryset import QuerySet

from controllers.config import ai_model_config_controller
from models.ai_task import AiTask
from models.asset import Asset
from schemas.asset import AssetCreate, AssetUpdate
from services.ai_task_executor import ai_task_executor
from utils.crud import CRUDBase
from utils.decorators import atomic
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.page import QueryParams


class AssetController(CRUDBase[Asset, AssetCreate, AssetUpdate]):
    def __init__(self):
        super().__init__(model=Asset)

    async def list(
        self,
        params: "QueryParams",
        response_model: Type[BaseModel],
        search_fields: Optional[list[str]] = None,
        base_query: Optional["QuerySet"] = None,
    ) -> dict[str, dict[str, int | Any] | Any]:
        """
        重写 list 方法，支持通过 chapter_id 过滤 JSON 数组。
        """
        if base_query is None:
            base_query = self.model.all()

        # 处理 chapter_id 过滤（Python 端过滤 JSON 数组，兼容 SQLite）
        # 前端传参: /api/asset?chapter_id=3
        if params.filters and "chapter_id" in params.filters:
            try:
                chapter_id = int(params.filters.pop("chapter_id"))
                all_assets = await self.model.all().values("id", "source_chapters")
                matching_ids = [
                    a["id"] for a in all_assets
                    if chapter_id in (a["source_chapters"] or [])
                ]
                base_query = base_query.filter(id__in=matching_ids)
            except (ValueError, TypeError):
                pass  # 忽略无效的 chapter_id

        return await super().list(params, response_model, search_fields, base_query)

    async def update(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().update(instance, obj_in)

    async def patch(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().patch(instance, obj_in)

    async def remove(self, asset_id: int) -> None:
        instance = await self.get(asset_id)
        await super().remove(instance)

    async def reference(self, asset_id: int) -> AiTask:
        """提交参考图生成任务。"""
        asset = await self.get(asset_id)

        # 1. 获取任务配置
        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.reference_image.value
        )

        # 2. 清理超时异常任务
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.reference_image)

        # 3. 检查活跃任务
        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.reference_image.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for t in active_tasks:
            # 检查 request_params 中的 asset_id
            if t.request_params.get("asset_id") == asset_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"该资产已有进行中的生成任务（{t.id}）",
                )

        # 4. 提交任务
        request_params = {
            "asset_id": asset.id,
            "novel_id": asset.novel_id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
        }

        task = await ai_task_executor.submit(
            AiTaskTypeEnum.reference_image, request_params
        )
        return task

asset_controller = AssetController()
