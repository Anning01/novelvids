"""Resume versioned tasks without resubmitting uncertain external operations."""

import asyncio
import logging
from utils.messages import localized_message
from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from services.creation_agent.skill_execution import WORKFLOW_VERSION

logger = logging.getLogger(__name__)


class ProductionRecovery:
    def __init__(self):
        self.worker = None
        self.running = {}

    async def recover(self):
        tasks = await AiTask.filter(status__in=[1, 2, 6])
        for task in tasks:
            if task.request_params.get(
                "workflow_version"
            ) != WORKFLOW_VERSION or task.request_params.get("parent_task_id"):
                continue
            if task.request_params.get("operation") == "video":
                from models.video import Video

                video = await Video.get_or_none(id=task.request_params.get("video_id"))
                if video and video.external_task_id:
                    await AiTask.filter(id=task.id).update(
                        status=2,
                        stage="waiting_media",
                        response_data={"video_id": video.id},
                    )
                    continue
            if await AgentOperation.filter(
                task_id=task.id, state__in=["running", "uncertain"], external=True
            ).exists():
                await AiTask.filter(id=task.id).update(
                    status=4,
                    stage="needs_review",
                    error_message=localized_message(
                        "提交结果待核对，系统不会重复提交",
                        _language=task.request_params.get("prompt_language", "en"),
                    ),
                )
                continue
            # Deterministic/model steps with no external-media submission can resume.
            await AgentOperation.filter(
                task_id=task.id, state="running", external=False
            ).update(state="pending")
            await AiTask.filter(id=task.id).update(status=6, stage="resuming")

    async def start(self):
        await self.recover()
        self.worker = asyncio.create_task(self.loop())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        for run in self.running.values():
            run.cancel()
        await asyncio.gather(*self.running.values(), return_exceptions=True)

    async def loop(self):
        from services.ai_task_executor import ai_task_executor

        while True:
            try:
                from models.video import Video
                from services.creation_agent.video_settlement import (
                    retry_video_settlements,
                )

                await retry_video_settlements()
                from services.creation_agent.review_evidence import retry_review_evidence
                await retry_review_evidence()

                for pending in await AiTask.filter(
                    stage__in=["billing_pending", "needs_review", "review_closed"]
                ).limit(20):
                    if pending.request_params.get(
                        "workflow_version"
                    ) == WORKFLOW_VERSION and (
                        pending.stage == "billing_pending"
                        or pending.request_params.get("billing_pending")
                    ):
                        await ai_task_executor._complete(
                            pending, pending.response_data or {}
                        )
                for waiting in await AiTask.filter(status=2, stage="waiting_media"):
                    if (
                        waiting.request_params.get("workflow_version")
                        != WORKFLOW_VERSION
                    ):
                        continue
                    video = await Video.get_or_none(
                        id=waiting.request_params.get("video_id")
                    )
                    if video and video.status == 3:
                        await ai_task_executor._complete(
                            waiting,
                            {
                                **(waiting.response_data or {}),
                                "video_id": video.id,
                                "url": video.url,
                            },
                        )
                    elif video and video.status in {4, 5}:
                        await ai_task_executor._fail(
                            waiting,
                            (video.metadata or {}).get("error") or "视频生成失败",
                            record_usage=False,
                        )
                self.running = {
                    key: value
                    for key, value in self.running.items()
                    if not value.done()
                }
                from services.creation_agent.sessions import agent_configuration

                capacity = (await agent_configuration()).production_concurrency
                if len(self.running) < capacity:
                    for task in (
                        await AiTask.filter(status__in=[1, 6])
                        .order_by("created_at")
                        .limit(20)
                    ):
                        if task.request_params.get(
                            "workflow_version"
                        ) != WORKFLOW_VERSION or task.request_params.get(
                            "parent_task_id"
                        ):
                            continue
                        if str(task.id) not in self.running:
                            self.running[str(task.id)] = asyncio.create_task(
                                ai_task_executor.run(task)
                            )
                        if len(self.running) >= capacity:
                            break
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    "Production recovery cycle failed: %s", type(error).__name__
                )
            await asyncio.sleep(2)


production_recovery = ProductionRecovery()
