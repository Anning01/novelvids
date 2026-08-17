"""计费流水写入器：从 model_config_id 快照定价并落 ModelUsageRecord。"""

import logging

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.billing.pricing import (
    compute_image_cost,
    compute_input_image_cost,
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
        duration_seconds=None,
        ai_task_id=None,
        video_id=None,
        team_id=None,
        user_id=None,
    ) -> ModelUsageRecord | None:
        try:
            # 消耗来源：团队自己的 Key 直连供应商不计入团队余额；
            # 平台模型（官方配置/未配置回退）按团队余额扣费
            cost_source = (
                "team_key"
                if config is not None and config.scope == "team"
                else "balance"
            )
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
                duration_seconds=duration_seconds,
                team_id=team_id,
                user_id=user_id,
                cost_source=cost_source,
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
        duration_seconds=None,
        ai_task_id=None,
        team_id=None,
        user_id=None,
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
            duration_seconds=duration_seconds,
            ai_task_id=ai_task_id,
            team_id=team_id,
            user_id=user_id,
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
        input_image_count: int = 0,
        status: int = TaskStatusEnum.completed.value,
        duration_seconds=None,
        ai_task_id=None,
        team_id=None,
        user_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        pricing = config.pricing if config else None
        usage = {
            "image_count": int(image_count or 0),
            "clarity": clarity,
            "input_image_count": int(input_image_count or 0),
        }
        cost = compute_image_cost(image_count, clarity, pricing) + compute_input_image_cost(
            input_image_count, pricing
        )
        return await self._create(
            novel_id=novel_id,
            task_type=task_type,
            billing_type="image",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            duration_seconds=duration_seconds,
            ai_task_id=ai_task_id,
            team_id=team_id,
            user_id=user_id,
        )

    async def record_video(
        self,
        *,
        novel_id: int,
        model_config_id=None,
        fallback_model=None,
        seconds: float = 0.0,
        resolution: str | None = None,
        input_video_seconds: float = 0.0,
        has_video_reference: bool = False,
        status: int = TaskStatusEnum.completed.value,
        duration_seconds=None,
        video_id=None,
        team_id=None,
        user_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = {
            "seconds": seconds,
            "resolution": resolution,
            "input_video_seconds": input_video_seconds,
            "has_video_reference": bool(has_video_reference),
        }
        cost = compute_video_cost(
            seconds,
            resolution,
            config.pricing if config else None,
            input_video_seconds=input_video_seconds,
            has_video_reference=has_video_reference,
        )
        return await self._create(
            novel_id=novel_id,
            task_type=AiTaskTypeEnum.video.value,
            billing_type="video",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            duration_seconds=duration_seconds,
            video_id=video_id,
            team_id=team_id,
            user_id=user_id,
        )


billing_recorder = BillingRecorder()


def _task_duration_seconds(task) -> float | None:
    if task.started_at and task.finished_at:
        return (task.finished_at - task.started_at).total_seconds()
    return None


async def record_ai_task_usage(task, result: dict | None, error: Exception | None = None) -> None:
    """AiTaskExecutor 完成/失败后的统一计费落点（含归属与余额扣减）。"""
    try:
        request_params = task.request_params or {}
        novel_id = request_params.get("novel_id")
        if novel_id is None:
            return
        task_type = task.task_type
        status = task.status
        duration = _task_duration_seconds(task)
        team_id = request_params.get("team_id")
        user_id = request_params.get("user_id")
        if task_type == AiTaskTypeEnum.reference_image.value:
            res = result or {}
            record = await billing_recorder.record_image(
                novel_id=novel_id,
                task_type=task_type,
                model_config_id=request_params.get("model_config_id"),
                fallback_model=request_params.get("model"),
                image_count=len(res.get("images") or []),
                clarity=request_params.get("clarity"),
                input_image_count=res.get("input_image_count", 0),
                status=status,
                duration_seconds=duration,
                ai_task_id=task.id,
                team_id=team_id,
                user_id=user_id,
            )
            await _consume_team_balance(record, team_id, user_id=user_id)
            return
        if task_type == AiTaskTypeEnum.project_analysis.value:
            res = result or {}
            token_usage = res.get("token_usage") or getattr(error, "usage", None) or {}
            record = await billing_recorder.record_text(
                novel_id=novel_id,
                task_type=task_type,
                model_config_id=res.get("llm_config_id"),
                fallback_model=res.get("llm_model"),
                token_usage=token_usage,
                status=status,
                duration_seconds=duration,
                ai_task_id=task.id,
                team_id=team_id,
                user_id=user_id,
            )
            await _consume_team_balance(record, team_id, user_id=user_id)
            image_usage = res.get("image_usage") or {}
            if image_usage:
                record = await billing_recorder.record_image(
                    novel_id=novel_id,
                    task_type=task_type,
                    model_config_id=res.get("image_config_id"),
                    fallback_model=res.get("image_model"),
                    image_count=image_usage.get("image_count", 0),
                    clarity=image_usage.get("clarity"),
                    status=status,
                    duration_seconds=duration,
                    ai_task_id=task.id,
                    team_id=team_id,
                    user_id=user_id,
                )
                await _consume_team_balance(record, team_id, user_id=user_id)
            return
        token_usage = (result or {}).get("token_usage") or getattr(error, "usage", None) or {}
        record = await billing_recorder.record_text(
            novel_id=novel_id,
            task_type=task_type,
            model_config_id=request_params.get("model_config_id"),
            fallback_model=request_params.get("model"),
            token_usage=token_usage,
            status=status,
            duration_seconds=duration,
            ai_task_id=task.id,
            team_id=team_id,
            user_id=user_id,
        )
        await _consume_team_balance(record, team_id, user_id=user_id)
    except Exception:
        logger.exception("billing record failed for task %s", getattr(task, "id", None))


async def _consume_team_balance(record, team_id, user_id=None) -> None:
    """计费后处理：仅平台模型（balance 来源）扣团队余额；成员累计消耗两种来源都记。"""
    if record is None or team_id is None:
        return
    from services.balance import accumulate_member_cost, consume

    if record.cost_source != "team_key":
        await consume(team_id, record.cost, usage_record_id=record.id)
    await accumulate_member_cost(team_id, user_id, record.cost)
