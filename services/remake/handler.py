"""重制拆解异步任务处理器。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Awaitable, Callable

from controllers.config import ai_model_config_controller
from fastapi import HTTPException
from models.ai_task import AiTask
from models.remake_source import RemakeSource
from services.ai_task_executor import BaseTaskHandler
from services.remake.gateway import RemakeVideoAnalysisError
from services.remake.materializer import RemakeMediaMaterializer, remake_media_materializer
from services.remake.persistence import RemakeResultPersistence, remake_result_persistence
from services.remake.pipeline import RemakeDecompositionPipeline, remake_decomposition_pipeline
from utils.enums import AiTaskTypeEnum

REMAKE_DECOMPOSITION_ERROR_CODE = "REMAKE_ANALYSIS_FAILED"
REMAKE_MODEL_UNAVAILABLE_ERROR_CODE = "REMAKE_ANALYSIS_MODEL_UNAVAILABLE"


class RemakeDecompositionError(RuntimeError):
    error_code = REMAKE_DECOMPOSITION_ERROR_CODE

    def __init__(
        self,
        *,
        error_code: str = REMAKE_DECOMPOSITION_ERROR_CODE,
        message: str = "重制视频拆解失败",
        usage: dict[str, int] | None = None,
    ) -> None:
        self.error_code = error_code
        super().__init__(f"{message}（错误代码：{error_code}）")
        self.usage = usage or {}


ModelResolver = Callable[..., Awaitable[Any]]


class RemakeDecompositionTaskHandler(BaseTaskHandler):
    def __init__(
        self,
        *,
        model_resolver: ModelResolver | None = None,
        materializer: RemakeMediaMaterializer = remake_media_materializer,
        pipeline: RemakeDecompositionPipeline = remake_decomposition_pipeline,
        persistence: RemakeResultPersistence = remake_result_persistence,
    ) -> None:
        self.model_resolver = model_resolver or ai_model_config_controller.get_active
        self.materializer = materializer
        self.pipeline = pipeline
        self.persistence = persistence

    async def execute(self, request_params: dict) -> dict:
        task_id = request_params.get("ai_task_id")
        source = await RemakeSource.get_or_none(
            id=request_params["remake_source_id"],
            novel_id=request_params["novel_id"],
            chapter_id=request_params["chapter_id"],
        )
        if source is None:
            raise RemakeDecompositionError()
        if source.team_id != request_params.get("team_id"):
            raise RemakeDecompositionError()

        source.media_status = "processing"
        await source.save(update_fields=["media_status", "updated_at"])
        try:
            model_config = await self.model_resolver(
                AiTaskTypeEnum.remake_decomposition.value,
                config_id=request_params.get("model_config_id"),
                team_id=request_params.get("team_id"),
            )
            if task_id:
                task_record = await AiTask.get_or_none(id=task_id)
                if task_record is not None:
                    task_record.request_params = {
                        **(task_record.request_params or request_params),
                        "model_config_id": model_config.id,
                        "model": model_config.model,
                    }
                    await task_record.save(
                        update_fields=["request_params", "updated_at"]
                    )

            async def report(value: int, stage: str) -> None:
                if task_id:
                    await AiTask.filter(id=task_id, progress__lte=int(value)).update(
                        progress=max(0, min(100, int(value))),
                        stage=stage,
                    )

            with TemporaryDirectory(prefix="remake-decomposition-") as temp_dir:
                work_dir = Path(temp_dir)
                source_path = await self.materializer.materialize(source, work_dir)
                result = await self.pipeline.run(
                    source_path=source_path,
                    model_config=model_config,
                    work_dir=work_dir,
                    progress=report,
                )
                summary = await self.persistence.persist(
                    source=source,
                    assets=result.assets,
                    prompt_document=result.prompt_document,
                    pipeline_metadata={
                        **result.metadata,
                        "attempt": int(request_params.get("attempt", 1) or 1),
                    },
                )
            return {
                **summary,
                "pipeline": result.metadata,
                "token_usage": result.token_usage,
                "llm_config_id": model_config.id,
                "llm_model": model_config.model,
            }
        except RemakeDecompositionError:
            await self._mark_failed(source)
            raise
        except RemakeVideoAnalysisError as error:
            await self._mark_failed(source)
            raise RemakeDecompositionError(
                error_code=error.error_code,
                message=error.user_message,
                usage=error.usage,
            ) from None
        except HTTPException as error:
            await self._mark_failed(source)
            if error.status_code == 404:
                raise RemakeDecompositionError(
                    error_code=REMAKE_MODEL_UNAVAILABLE_ERROR_CODE,
                    message="未配置可用的重制拆解模型",
                ) from None
            raise RemakeDecompositionError() from None
        except Exception as error:
            await self._mark_failed(source)
            raise RemakeDecompositionError(
                usage=getattr(error, "usage", None) or {}
            ) from None

    @staticmethod
    async def _mark_failed(source: RemakeSource) -> None:
        await RemakeSource.filter(id=source.id).update(media_status="failed")
        source.media_status = "failed"


remake_decomposition_handler = RemakeDecompositionTaskHandler()
