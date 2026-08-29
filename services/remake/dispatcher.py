"""重制项目多集拆解任务的受控并发投递。"""

from __future__ import annotations

import asyncio
import logging

from config import settings
from services.ai_task_executor import AiTaskExecutor, ai_task_executor

logger = logging.getLogger(__name__)


class RemakeTaskDispatcher:
    def __init__(
        self,
        *,
        executor: AiTaskExecutor | None = None,
        concurrency: int | None = None,
    ) -> None:
        self.executor = executor or ai_task_executor
        self.concurrency = max(
            1,
            int(concurrency or settings.REMAKE_ANALYSIS_CONCURRENCY),
        )

    async def run(self, tasks: list) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(task) -> None:
            async with semaphore:
                try:
                    await self.executor.run(task)
                except Exception:
                    logger.exception(
                        "Failed to dispatch remake task: %s",
                        getattr(task, "id", "unknown"),
                    )
                    await self.executor.fail_dispatch(task)

        await asyncio.gather(
            *(run_one(task) for task in tasks),
            return_exceptions=True,
        )


remake_task_dispatcher = RemakeTaskDispatcher()
