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


async def record_ai_task_usage(task, result: dict | None, error: Exception | None = None) -> None:
    """AiTaskExecutor 完成/失败后的统一计费落点。"""
    try:
        request_params = task.request_params or {}
        novel_id = request_params.get("novel_id")
        if novel_id is None:
            return
        task_type = task.task_type
        status = task.status
        if task_type == AiTaskTypeEnum.reference_image.value:
            await billing_recorder.record_image(
                novel_id=novel_id,
                task_type=task_type,
                model_config_id=request_params.get("model_config_id"),
                fallback_model=request_params.get("model"),
                image_count=len((result or {}).get("images") or []),
                clarity=request_params.get("clarity"),
                status=status,
                ai_task_id=task.id,
            )
            return
        if task_type == AiTaskTypeEnum.project_analysis.value:
            res = result or {}
            token_usage = res.get("token_usage") or getattr(error, "usage", None) or {}
            await billing_recorder.record_text(
                novel_id=novel_id,
                task_type=task_type,
                model_config_id=res.get("llm_config_id"),
                fallback_model=res.get("llm_model"),
                token_usage=token_usage,
                status=status,
                ai_task_id=task.id,
            )
            image_usage = res.get("image_usage") or {}
            if image_usage:
                await billing_recorder.record_image(
                    novel_id=novel_id,
                    task_type=task_type,
                    model_config_id=res.get("image_config_id"),
                    fallback_model=res.get("image_model"),
                    image_count=image_usage.get("image_count", 0),
                    clarity=image_usage.get("clarity"),
                    status=status,
                    ai_task_id=task.id,
                )
            return
        token_usage = (result or {}).get("token_usage") or getattr(error, "usage", None) or {}
        await billing_recorder.record_text(
            novel_id=novel_id,
            task_type=task_type,
            model_config_id=request_params.get("model_config_id"),
            fallback_model=request_params.get("model"),
            token_usage=token_usage,
            status=status,
            ai_task_id=task.id,
        )
    except Exception:
        logger.exception("billing record failed for task %s", getattr(task, "id", None))
