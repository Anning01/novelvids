"""分镜生成任务服务。

提供异步分镜生成，支持：
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
from novelvids.domain.models.storyboard import (
    AspectRatio,
    StoryboardGenerateRequest,
    VideoStyle,
)
from novelvids.domain.services.llm_client import OpenAICompatibleClient
from novelvids.domain.services.storyboard.service import StoryboardService
from novelvids.infrastructure.database.models import (
    AssetModel,
    ChapterAssetModel,
    ChapterModel,
    StoryboardTaskModel,
    TaskStatus,
)


class StoryboardTaskService:
    """分镜生成任务服务。

    负责：
    1. 创建和管理分镜生成任务
    2. 执行后台生成
    3. 保存生成结果到 Chapter metadata
    4. 进度更新和错误处理
    """

    def __init__(self):
        self._llm_client: OpenAICompatibleClient | None = None
        self._storyboard_service: StoryboardService | None = None

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

    @property
    def storyboard_service(self) -> StoryboardService:
        """懒加载分镜服务。"""
        if self._storyboard_service is None:
            self._storyboard_service = StoryboardService(self.llm_client)
        return self._storyboard_service

    async def create_task(
        self,
        chapter_id: UUID,
        target_platform: str = "veo",
        max_shot_duration: float = 8.0,
        style_preset: str = "cinematic",
        aspect_ratio: str = "16:9",
        include_audio: bool = True,
        timeout_seconds: int = 600,  # 调试模式：10分钟超时
        max_retries: int = 3,
    ) -> StoryboardTaskModel:
        """创建分镜生成任务。

        如果已存在进行中的任务，返回现有任务。
        """
        # 检查是否已有进行中的任务
        existing = await StoryboardTaskModel.filter(
            chapter_id=chapter_id,
            status__in=[TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.QUEUED],
        ).first()

        if existing:
            return existing

        # 创建新任务
        task = await StoryboardTaskModel.create(
            chapter_id=chapter_id,
            target_platform=target_platform,
            max_shot_duration=max_shot_duration,
            style_preset=style_preset,
            aspect_ratio=aspect_ratio,
            include_audio=include_audio,
            status=TaskStatus.PENDING,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

        return task

    async def get_task(self, task_id: UUID) -> StoryboardTaskModel | None:
        """获取任务详情。"""
        return await StoryboardTaskModel.get_or_none(id=task_id)

    async def get_chapter_task(self, chapter_id: UUID) -> StoryboardTaskModel | None:
        """获取章节的最新分镜生成任务。"""
        return await StoryboardTaskModel.filter(
            chapter_id=chapter_id
        ).order_by("-created_at").first()

    async def execute_task(self, task_id: UUID) -> StoryboardTaskModel:
        """执行分镜生成任务（在后台运行）。

        这个方法会被 FastAPI BackgroundTasks 调用。
        """
        logger.info(f"[Task {task_id}] 开始执行分镜生成任务")

        task = await StoryboardTaskModel.get_or_none(id=task_id).prefetch_related(
            "chapter", "chapter__novel"
        )
        if task is None:
            logger.error(f"[Task {task_id}] 任务不存在")
            raise ValueError(f"Task {task_id} not found")

        # 标记为运行中
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.progress = 5
        task.message = "正在准备生成分镜..."
        await task.save()
        logger.info(f"[Task {task_id}] 状态更新为 RUNNING")

        try:
            # 需要 await 访问外键关系
            chapter = await task.chapter
            logger.info(f"[Task {task_id}] 章节: {chapter.title} (ID: {chapter.id})")

            # 获取资产
            task.progress = 10
            task.message = "正在加载资产数据..."
            await task.save()

            person_assets, scene_assets, item_assets = await self._load_assets(
                chapter.id, chapter.novel_id
            )
            logger.info(f"[Task {task_id}] 加载资产完成: 人物={len(person_assets)}, 场景={len(scene_assets)}, 物品={len(item_assets)}")

            # 生成分镜
            task.progress = 20
            task.message = "正在调用 AI 生成分镜..."
            await task.save()
            logger.info(f"[Task {task_id}] 开始调用 LLM 生成分镜...")

            result = await self._generate_storyboard(task, chapter, person_assets, scene_assets, item_assets)
            logger.info(f"[Task {task_id}] LLM 返回结果: {result.shot_count} 个镜头, 总时长 {result.total_duration}s")

            # 保存到章节元数据
            task.progress = 90
            task.message = "正在保存分镜数据..."
            await task.save()

            storyboard_data = result.storyboard.model_dump(mode="json")
            chapter.metadata["storyboard"] = storyboard_data
            chapter.scene_count = result.shot_count
            await chapter.save()
            logger.info(f"[Task {task_id}] 分镜数据已保存到章节 metadata")

            # 完成
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            task.message = f"生成完成，共 {result.shot_count} 个镜头"
            task.result = {
                "shot_count": result.shot_count,
                "total_duration": result.total_duration,
                "warnings": result.warnings,
            }
            task.completed_at = datetime.now(UTC)
            await task.save()
            logger.info(f"[Task {task_id}] ✅ 任务完成!")

        except asyncio.TimeoutError:
            logger.error(f"[Task {task_id}] ❌ 生成超时 (timeout={task.timeout_seconds}s)")
            task.status = TaskStatus.FAILED
            task.error = "生成超时"
            task.message = "操作超时，请重试"
            await task.save()
            await self._maybe_retry(task)

        except Exception as e:
            logger.exception(f"[Task {task_id}] ❌ 生成失败: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.message = f"生成失败: {str(e)[:100]}"
            await task.save()
            await self._maybe_retry(task)

        return task

    async def _load_assets(
        self, chapter_id: UUID, novel_id: UUID
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """加载章节关联的资产。"""
        chapter_assets = await ChapterAssetModel.filter(
            chapter_id=chapter_id
        ).prefetch_related("asset").all()

        person_assets = []
        scene_assets = []
        item_assets = []

        for ca in chapter_assets:
            asset = await ca.asset
            asset_dict = {
                "id": str(asset.id),
                "canonical_name": asset.canonical_name,
                "aliases": asset.aliases,
                "description": asset.description,
                "base_traits": asset.base_traits,
                "main_image": asset.main_image,
            }
            if asset.asset_type == "person":
                person_assets.append(asset_dict)
            elif asset.asset_type == "scene":
                scene_assets.append(asset_dict)
            elif asset.asset_type == "item":
                item_assets.append(asset_dict)

        # 如果没有章节级资产，尝试获取全局资产
        if not person_assets and not scene_assets and not item_assets:
            global_assets = await AssetModel.filter(
                novel_id=novel_id, is_global=True
            ).all()
            for asset in global_assets:
                asset_dict = {
                    "id": str(asset.id),
                    "canonical_name": asset.canonical_name,
                    "aliases": asset.aliases,
                    "description": asset.description,
                    "base_traits": asset.base_traits,
                    "main_image": asset.main_image,
                }
                if asset.asset_type == "person":
                    person_assets.append(asset_dict)
                elif asset.asset_type == "scene":
                    scene_assets.append(asset_dict)
                elif asset.asset_type == "item":
                    item_assets.append(asset_dict)

        return person_assets, scene_assets, item_assets

    async def _generate_storyboard(
        self,
        task: StoryboardTaskModel,
        chapter: ChapterModel,
        person_assets: list[dict],
        scene_assets: list[dict],
        item_assets: list[dict],
    ):
        """执行分镜生成。"""
        # 解析参数
        try:
            style_preset = VideoStyle(task.style_preset)
        except ValueError:
            style_preset = VideoStyle.CINEMATIC

        try:
            aspect_ratio = AspectRatio(task.aspect_ratio)
        except ValueError:
            aspect_ratio = AspectRatio.RATIO_16_9

        request = StoryboardGenerateRequest(
            chapter_id=chapter.id,
            chapter_content=chapter.content or "",
            person_assets=person_assets,
            scene_assets=scene_assets,
            item_assets=item_assets,
            max_shot_duration=task.max_shot_duration,
            target_platform=task.target_platform,
            style_preset=style_preset,
            aspect_ratio=aspect_ratio,
            include_audio=task.include_audio,
        )

        # 执行生成（带超时）
        result = await asyncio.wait_for(
            self.storyboard_service.generate_storyboard(
                chapter_id=chapter.id,
                chapter_number=chapter.number,
                chapter_title=chapter.title,
                chapter_content=chapter.content or "",
                person_assets=person_assets,
                scene_assets=scene_assets,
                item_assets=item_assets,
                request=request,
            ),
            timeout=task.timeout_seconds,
        )

        # 更新进度
        task.progress = 80
        task.message = f"已生成 {result.shot_count} 个镜头"
        await task.save()

        return result

    async def _maybe_retry(self, task: StoryboardTaskModel) -> None:
        """检查是否可以重试，如果可以则创建新任务。"""
        if task.retry_count < task.max_retries:
            new_task = await StoryboardTaskModel.create(
                chapter_id=task.chapter_id,
                target_platform=task.target_platform,
                max_shot_duration=task.max_shot_duration,
                style_preset=task.style_preset,
                aspect_ratio=task.aspect_ratio,
                include_audio=task.include_audio,
                status=TaskStatus.PENDING,
                retry_count=task.retry_count + 1,
                max_retries=task.max_retries,
                timeout_seconds=task.timeout_seconds,
            )
            task.result = {"retry_task_id": str(new_task.id)}
            await task.save()

    async def cleanup_stale_tasks(self, older_than_minutes: int = 30) -> int:
        """清理过期的任务。"""
        cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
        count = await StoryboardTaskModel.filter(
            status__in=[TaskStatus.PENDING, TaskStatus.RUNNING],
            created_at__lt=cutoff,
        ).update(status=TaskStatus.FAILED, error="任务超时被清理")
        return count


# 全局服务实例
storyboard_task_service = StoryboardTaskService()
