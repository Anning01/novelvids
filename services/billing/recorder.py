"""计费流水写入器：从 model_config_id 快照定价并落 ModelUsageRecord。"""

import logging

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.billing.pricing import (
    compute_image_cost,
    compute_text_cost,
    compute_video_cost,
    normalize_token_usage,
)
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

logger = logging.getLogger(__name__)


class BillingRecorder:
    @staticmethod
    async def _config(model_config_id):
        if model_config_id is None:
            return None
        return await AiModelConfig.get_or_none(id=model_config_id)

    async def _create(
        self,
        *,
        novel_id: int,
        task_type: int,
        billing_type: str,
        config: AiModelConfig | None,
        fallback_model: str | None,
        usage: dict,
        cost,
        status: int,
        ai_task_id=None,
        video_id=None,
    ) -> ModelUsageRecord | None:
        try:
            return await ModelUsageRecord.create(
                novel_id=novel_id,
                task_type=task_type,
                billing_type=billing_type,
                ai_task_id=ai_task_id,
                video_id=video_id,
                model_config_id=config.id if config else None,
                model_name=config.name if config else None,
                model=(config.model if config else fallback_model) or "",
                model_type=(config.image_model_type or config.video_model_type) if config else None,
                pricing_snapshot=config.pricing if config else None,
                usage=usage,
                cost=cost,
                currency="CNY",
                status=status,
            )
        except Exception:
            logger.exception(
                "billing record write failed task_type=%s billing_type=%s",
                task_type,
                billing_type,
            )
            return None

    async def record_text(
        self,
        *,
        novel_id: int,
        task_type: int,
        model_config_id=None,
        fallback_model=None,
        token_usage=None,
        status: int = TaskStatusEnum.completed.value,
        ai_task_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = normalize_token_usage(token_usage)
        cost = compute_text_cost(token_usage, config.pricing if config else None)
        return await self._create(
            novel_id=novel_id,
            task_type=task_type,
            billing_type="text",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            ai_task_id=ai_task_id,
        )

    async def record_image(
        self,
        *,
        novel_id: int,
        task_type: int,
        model_config_id=None,
        fallback_model=None,
        image_count: int = 0,
        clarity: str | None = None,
        status: int = TaskStatusEnum.completed.value,
        ai_task_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = {"image_count": int(image_count or 0), "clarity": clarity}
        cost = compute_image_cost(image_count, clarity, config.pricing if config else None)
        return await self._create(
            novel_id=novel_id,
            task_type=task_type,
            billing_type="image",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            ai_task_id=ai_task_id,
        )

    async def record_video(
        self,
        *,
        novel_id: int,
        model_config_id=None,
        fallback_model=None,
        seconds: float = 0.0,
        resolution: str | None = None,
        status: int = TaskStatusEnum.completed.value,
        video_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = {"seconds": seconds, "resolution": resolution}
        cost = compute_video_cost(seconds, resolution, config.pricing if config else None)
        return await self._create(
            novel_id=novel_id,
            task_type=AiTaskTypeEnum.video.value,
            billing_type="video",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            video_id=video_id,
        )


billing_recorder = BillingRecorder()
