import abc
import asyncio
import logging
from datetime import datetime, timezone

from models.ai_task import AiTask
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

logger = logging.getLogger(__name__)


# 不同任务类型的超时时间（秒）
TASK_TIMEOUT: dict[AiTaskTypeEnum, int] = {
    AiTaskTypeEnum.extraction: 600,
    AiTaskTypeEnum.reference_image: 600,
    AiTaskTypeEnum.storyboard: 900,
    AiTaskTypeEnum.video: 600,
}


class BaseTaskHandler(abc.ABC):
    """任务处理器基类，每种任务类型实现一个子类。"""

    @abc.abstractmethod
    async def execute(self, request_params: dict) -> dict:
        """
        执行任务，返回结果字典。

        Args:
            request_params: 任务请求参数。

        Returns:
            结果数据字典，写入 response_data。

        Raises:
            Exception: 任务执行失败时抛出异常。
        """


class AiTaskExecutor:
    """AI 任务执行器 - 调度并执行 AI 任务。"""

    def __init__(self):
        self._handlers: dict[AiTaskTypeEnum, BaseTaskHandler] = {}
        # 每个任务类型一个信号量，控制并发
        self._semaphores: dict[AiTaskTypeEnum, asyncio.Semaphore] = {}

    def register(self, task_type: AiTaskTypeEnum, handler: BaseTaskHandler):
        """注册任务处理器。"""
        self._handlers[task_type] = handler

    def get_semaphore(self, task_type: AiTaskTypeEnum, concurrency: int) -> asyncio.Semaphore:
        """获取/更新任务类型的并发信号量。"""
        existing = self._semaphores.get(task_type)
        if existing is None or existing._value != concurrency:
            self._semaphores[task_type] = asyncio.Semaphore(concurrency)
        return self._semaphores[task_type]

    async def cleanup_stale_tasks(self, task_type: AiTaskTypeEnum):
        """
        清理同类型的异常任务：已超时但状态仍为 pending/running 的任务。

        超时以 started_at（running）或 created_at（pending）为起点计算。
        """
        timeout = TASK_TIMEOUT.get(task_type, 60)
        now = datetime.now(timezone.utc)

        stale_tasks = await AiTask.filter(
            task_type=task_type.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )

        for task in stale_tasks:
            # running 任务以 started_at 为基准，pending 任务以 created_at 为基准
            baseline = task.started_at if task.started_at else task.created_at
            if baseline and (now - baseline).total_seconds() > timeout:
                logger.warning("Cleaning stale task #%s (status=%s)", task.id, task.status)
                await self._fail(task, f"异常任务清理：超时（{timeout}s）")

    async def submit(self, task_type: AiTaskTypeEnum, request_params: dict) -> AiTask:
        """
        提交任务，写入数据库，返回任务记录。

        前端可凭 task.id 轮询查询任务状态。
        """
        task = await AiTask.create(
            task_type=task_type.value,
            request_params=request_params,
            status=TaskStatusEnum.pending.value,
        )
        return task

    async def run(self, task: AiTask):
        """
        执行单个任务（在 BackgroundTask 中调用）。

        流程：cleanup -> pending -> running -> completed / failed
        """
        task_type = AiTaskTypeEnum(task.task_type)
        handler = self._handlers.get(task_type)
        if handler is None:
            await self._fail(task, f"未注册的任务类型: {task_type.nickname}")
            return

        # 执行前清理同类型异常任务
        await self.cleanup_stale_tasks(task_type)

        # 重新加载任务状态（可能被清理逻辑改了，或前端取消了）
        await task.refresh_from_db()
        if task.status != TaskStatusEnum.pending.value:
            logger.info("Task #%s skipped (status=%s)", task.id, task.status)
            return

        timeout = TASK_TIMEOUT.get(task_type, 600)

        # 标记为执行中
        task.status = TaskStatusEnum.running.value
        task.started_at = datetime.now(timezone.utc)
        await task.save(update_fields=["status", "started_at", "updated_at"])

        try:
            result = await asyncio.wait_for(
                handler.execute(task.request_params),
                timeout=timeout,
            )
            await self._complete(task, result)
        except asyncio.TimeoutError:
            await self._fail(task, f"任务超时（{timeout}s）")
        except Exception as e:
            logger.exception("AI task #%s failed", task.id)
            await self._fail(task, str(e))

    async def submit_and_run(
        self, task_type: AiTaskTypeEnum, request_params: dict
    ) -> AiTask:
        """提交并立即执行，适合在 BackgroundTask 中使用。"""
        task = await self.submit(task_type, request_params)
        await self.run(task)
        return task

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _complete(self, task: AiTask, result: dict):
        task.status = TaskStatusEnum.completed.value
        task.response_data = result
        task.finished_at = datetime.now(timezone.utc)
        await task.save(
            update_fields=["status", "response_data", "finished_at", "updated_at"]
        )

    async def _fail(self, task: AiTask, error_message: str):
        task.status = TaskStatusEnum.failed.value
        task.error_message = error_message
        task.finished_at = datetime.now(timezone.utc)
        await task.save(
            update_fields=["status", "error_message", "finished_at", "updated_at"]
        )


# 全局单例，在应用启动时注册各 handler
ai_task_executor = AiTaskExecutor()
