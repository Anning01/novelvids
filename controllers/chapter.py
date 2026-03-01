from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from schemas.chapter import ChapterCreate, ChapterUpdate
from services.ai_task_executor import ai_task_executor
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class ChapterController(CRUDBase[Chapter, ChapterCreate, ChapterUpdate]):
    def __init__(self):
        super().__init__(model=Chapter)

    async def create(self, obj_in: ChapterCreate) -> Chapter:
        """创建章节并更新小说的 total_chapters。

        number 未传时，自动取该小说下最大 number + 1。
        """
        if obj_in.number is None:
            max_row = await Chapter.filter(novel_id=obj_in.novel_id).order_by("-number").first()
            obj_in.number = (max_row.number + 1) if max_row else 1

        if not obj_in.name:
            obj_in.name = f"第{obj_in.number}章"

        chapter = await super().create(obj_in)

        # 更新小说的总章节数
        novel = await Novel.get(id=chapter.novel_id)
        if novel:
            count = await Chapter.filter(novel_id=chapter.novel_id).count()
            await novel.update_from_dict({"total_chapters": count})
            await novel.save()

        return chapter

    async def update(self, chapter_id: int, obj_in: ChapterUpdate) -> Chapter:
        instance = await self.get(chapter_id)
        return await super().update(instance, obj_in)

    async def patch(self, chapter_id: int, obj_in: ChapterUpdate) -> Chapter:
        instance = await self.get(chapter_id)
        return await super().patch(instance, obj_in)

    async def remove(self, chapter_id: int) -> None:
        """删除章节并更新小说的 total_chapters"""
        instance = await self.get(chapter_id)
        novel_id = instance.novel_id
        await super().remove(instance)

        # 更新小说的总章节数
        novel = await Novel.get(id=novel_id)
        if novel:
            count = await Chapter.filter(novel_id=novel_id).count()
            await novel.update_from_dict({"total_chapters": count})
            await novel.save()

    async def extract(self, chapter_id: int) -> AiTask:
        """提交提取任务，返回任务记录供前端轮询。"""
        chapter = await self.get(chapter_id)

        # 1. 获取提取任务的启用配置
        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.extraction.value
        )

        # 2. 先清理超时异常任务，再检查是否有活跃任务
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.extraction.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for t in active_tasks:
            if t.request_params.get("chapter_id") == chapter_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"该章节已有进行中的提取任务（{t.id}）",
                )

        # 3. 提交任务（BackgroundTask 中执行）
        request_params = {
            "chapter_id": chapter.id,
            "novel_id": chapter.novel_id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "concurrency": config.concurrency,
        }
        task = await ai_task_executor.submit(
            AiTaskTypeEnum.extraction, request_params
        )
        return task


chapter_controller = ChapterController()
