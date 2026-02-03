"""资产提取任务服务。

提供分离式的资产提取（人物/场景/物品），支持：
- 后台任务执行
- 进度追踪
- 超时控制和重试
- 结果缓存
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

logger = logging.getLogger(__name__)

from novelvids.core.config import settings
from novelvids.domain.services.llm_client import OpenAICompatibleClient
from novelvids.domain.services.extraction import (
    ItemExtractor,
    PersonExtractor,
    SceneExtractor,
)
from novelvids.domain.services.extraction.base import ExtractedEntity
from novelvids.infrastructure.database.models import (
    AssetModel,
    AssetType,
    ChapterAssetModel,
    ChapterModel,
    ExtractionTaskModel,
    ExtractionTaskType,
    TaskStatus,
)


class ExtractionTaskService:
    """资产提取任务服务。

    负责：
    1. 创建和管理提取任务
    2. 执行后台提取
    3. 保存提取结果到 Asset 表
    4. 进度更新和错误处理
    """

    def __init__(self):
        self._llm_client: OpenAICompatibleClient | None = None

    @property
    def llm_client(self) -> OpenAICompatibleClient:
        """懒加载 LLM 客户端。"""
        if self._llm_client is None:
            self._llm_client = OpenAICompatibleClient(
                api_key=settings.llm.api_key,
                base_url=settings.llm.base_url,
                model_name=settings.llm.model_name,
            )
        return self._llm_client

    async def create_task(
        self,
        chapter_id: UUID,
        task_type: ExtractionTaskType,
        timeout_seconds: int = 120,
        max_retries: int = 3,
    ) -> ExtractionTaskModel:
        """创建提取任务。

        如果已存在进行中的同类型任务，返回现有任务。
        """
        logger.info(f"[Extraction] 创建任务请求: chapter_id={chapter_id}, type={task_type.value}")

        # 检查是否已有进行中的任务
        existing = await ExtractionTaskModel.filter(
            chapter_id=chapter_id,
            task_type=task_type,
            status__in=[TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.QUEUED],
        ).first()

        if existing:
            logger.info(f"[Extraction] 已存在进行中的任务: task_id={existing.id}, status={existing.status}")
            return existing

        # 创建新任务
        task = await ExtractionTaskModel.create(
            chapter_id=chapter_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        logger.info(f"[Extraction] 新任务已创建: task_id={task.id}, type={task_type.value}")

        return task

    async def get_task(self, task_id: UUID) -> ExtractionTaskModel | None:
        """获取任务详情。"""
        return await ExtractionTaskModel.get_or_none(id=task_id)

    async def get_chapter_tasks(
        self, chapter_id: UUID
    ) -> dict[str, ExtractionTaskModel | None]:
        """获取章节的所有提取任务状态。"""
        tasks = await ExtractionTaskModel.filter(chapter_id=chapter_id).order_by(
            "-created_at"
        )

        # 按类型分组，取最新的
        result: dict[str, ExtractionTaskModel | None] = {
            "person": None,
            "scene": None,
            "item": None,
        }

        for task in tasks:
            task_type = task.task_type.value
            if result[task_type] is None:
                result[task_type] = task

        return result

    async def execute_task(self, task_id: UUID) -> ExtractionTaskModel:
        """执行提取任务（在后台运行）。

        这个方法会被 FastAPI BackgroundTasks 调用。
        """
        logger.info(f"[Task {task_id}] ========== 开始执行提取任务 ==========")

        task = await ExtractionTaskModel.get_or_none(id=task_id).prefetch_related(
            "chapter", "chapter__novel"
        )
        if task is None:
            logger.error(f"[Task {task_id}] 任务不存在!")
            raise ValueError(f"Task {task_id} not found")

        logger.info(f"[Task {task_id}] 任务类型: {task.task_type.value}, 重试次数: {task.retry_count}/{task.max_retries}")

        # 标记为运行中
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.progress = 10
        task.message = "正在准备提取..."
        await task.save()
        logger.info(f"[Task {task_id}] 状态更新为 RUNNING")

        try:
            # 执行提取
            chapter = task.chapter
            logger.info(f"[Task {task_id}] 章节: {chapter.title} (ID: {chapter.id})")
            logger.info(f"[Task {task_id}] 章节内容长度: {len(chapter.content or '')} 字符")

            entities = await self._extract_entities(task, chapter)
            logger.info(f"[Task {task_id}] 提取完成: 共 {len(entities)} 个实体")

            # 更新进度
            task.progress = 70
            task.message = "正在保存资产..."
            await task.save()
            logger.info(f"[Task {task_id}] 开始保存到数据库...")

            # 保存到数据库
            await self._save_entities_to_db(task, chapter, entities)
            logger.info(f"[Task {task_id}] 数据库保存完成")

            # 完成
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.message = f"提取完成，共 {len(entities)} 个实体"
            task.result = {"count": len(entities), "entities": [e.to_dict() for e in entities]}
            task.completed_at = datetime.now(UTC)
            await task.save()
            logger.info(f"[Task {task_id}] ✅ 任务完成! 共提取 {len(entities)} 个{self._get_type_name(task.task_type)}")

        except asyncio.TimeoutError:
            logger.error(f"[Task {task_id}] ❌ 提取超时 (timeout={task.timeout_seconds}s)")
            task.status = TaskStatus.FAILED
            task.error = "提取超时"
            task.message = "操作超时，请重试"
            await task.save()
            # 检查是否可以重试
            await self._maybe_retry(task)

        except Exception as e:
            logger.exception(f"[Task {task_id}] ❌ 提取失败: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.message = f"提取失败: {str(e)[:100]}"
            await task.save()
            # 检查是否可以重试
            await self._maybe_retry(task)

        logger.info(f"[Task {task_id}] ========== 任务执行结束 ==========")
        return task

    async def _extract_entities(
        self, task: ExtractionTaskModel, chapter: ChapterModel
    ) -> list[ExtractedEntity]:
        """根据任务类型执行提取。"""
        task.progress = 30
        task.message = f"正在提取{self._get_type_name(task.task_type)}..."
        await task.save()
        logger.info(f"[Task {task.id}] 开始调用 LLM 提取 {task.task_type.value}...")

        # 选择提取器
        if task.task_type == ExtractionTaskType.PERSON:
            extractor = PersonExtractor(self.llm_client)
        elif task.task_type == ExtractionTaskType.SCENE:
            extractor = SceneExtractor(self.llm_client)
        else:
            extractor = ItemExtractor(self.llm_client)

        # 执行提取（带超时）
        logger.info(f"[Task {task.id}] 调用 extractor.extract(), timeout={task.timeout_seconds}s")
        entities = await asyncio.wait_for(
            extractor.extract(chapter.content or "", chapter.number),
            timeout=task.timeout_seconds,
        )

        task.progress = 60
        task.message = f"提取到 {len(entities)} 个{self._get_type_name(task.task_type)}"
        await task.save()
        logger.info(f"[Task {task.id}] LLM 返回 {len(entities)} 个实体")

        return entities

    async def _save_entities_to_db(
        self,
        task: ExtractionTaskModel,
        chapter: ChapterModel,
        entities: list[ExtractedEntity],
    ) -> None:
        """将提取的实体保存到数据库。

        1. 创建或更新 AssetModel
        2. 创建 ChapterAssetModel 关联
        """
        novel_id = chapter.novel_id
        asset_type = AssetType(task.task_type.value)

        for i, entity in enumerate(entities):
            logger.debug(f"[Task {task.id}] 保存实体 {i+1}/{len(entities)}: {entity.name}")

            # 查找或创建资产
            asset = await AssetModel.get_or_none(
                novel_id=novel_id,
                asset_type=asset_type,
                canonical_name=entity.name,
            )

            if asset is None:
                # 创建新资产
                asset = await AssetModel.create(
                    novel_id=novel_id,
                    asset_type=asset_type,
                    canonical_name=entity.name,
                    aliases=entity.aliases,
                    description=entity.description,
                    base_traits=entity.base_traits,
                    is_global=True,
                    source_chapters=[chapter.number],
                    last_updated_chapter=chapter.number,
                )
                logger.debug(f"[Task {task.id}] 创建新资产: {entity.name}")
            else:
                # 更新现有资产
                # 合并别名
                merged_aliases = list(set(asset.aliases + entity.aliases))
                # 合并章节来源
                source_chapters = list(set(asset.source_chapters + [chapter.number]))

                asset.aliases = merged_aliases
                asset.source_chapters = sorted(source_chapters)
                asset.last_updated_chapter = max(
                    asset.last_updated_chapter, chapter.number
                )
                # 只在描述为空时更新
                if not asset.description and entity.description:
                    asset.description = entity.description
                if not asset.base_traits and entity.base_traits:
                    asset.base_traits = entity.base_traits
                await asset.save()
                logger.debug(f"[Task {task.id}] 更新资产: {entity.name}")

            # 创建章节-资产关联
            chapter_asset = await ChapterAssetModel.get_or_none(
                chapter_id=chapter.id,
                asset_id=asset.id,
            )

            if chapter_asset is None:
                await ChapterAssetModel.create(
                    chapter_id=chapter.id,
                    asset_id=asset.id,
                    state_description=entity.description,
                    state_traits=entity.base_traits,
                    appearances=entity.appearances,
                )
            else:
                # 更新出现位置
                chapter_asset.appearances = entity.appearances
                chapter_asset.state_description = entity.description
                chapter_asset.state_traits = entity.base_traits
                await chapter_asset.save()

    async def _maybe_retry(self, task: ExtractionTaskModel) -> ExtractionTaskModel | None:
        """检查是否可以重试，如果可以则创建新任务并立即执行。

        返回新创建的任务，供调用者添加到后台执行。
        """
        if task.retry_count < task.max_retries:
            logger.info(f"[Task {task.id}] 准备重试 ({task.retry_count + 1}/{task.max_retries})...")

            # 创建重试任务
            new_task = await ExtractionTaskModel.create(
                chapter_id=task.chapter_id,
                task_type=task.task_type,
                status=TaskStatus.PENDING,
                retry_count=task.retry_count + 1,
                max_retries=task.max_retries,
                timeout_seconds=task.timeout_seconds,
            )

            # 返回新任务 ID 供外部处理
            task.result = {"retry_task_id": str(new_task.id)}
            await task.save()

            logger.info(f"[Task {task.id}] 重试任务已创建: new_task_id={new_task.id}")

            # 直接在这里执行重试任务（递归调用）
            # 这样避免了需要外部再次调度的问题
            logger.info(f"[Task {new_task.id}] 开始执行重试任务...")
            await self.execute_task(new_task.id)

            return new_task
        else:
            logger.warning(f"[Task {task.id}] 已达到最大重试次数 ({task.max_retries})，不再重试")
            return None

    def _get_type_name(self, task_type: ExtractionTaskType) -> str:
        """获取任务类型的中文名称。"""
        names = {
            ExtractionTaskType.PERSON: "人物",
            ExtractionTaskType.SCENE: "场景",
            ExtractionTaskType.ITEM: "物品",
        }
        return names.get(task_type, "实体")

    async def cleanup_stale_tasks(self, older_than_minutes: int = 30) -> int:
        """清理过期的任务。"""
        cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        count = await ExtractionTaskModel.filter(
            status__in=[TaskStatus.PENDING, TaskStatus.RUNNING],
            created_at__lt=cutoff,
        ).update(status=TaskStatus.FAILED, error="任务超时被清理")
        if count > 0:
            logger.info(f"[Extraction] 清理了 {count} 个过期任务")
        return count


# 全局服务实例
extraction_task_service = ExtractionTaskService()
