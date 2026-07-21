from fastapi import HTTPException

from models.ai_task import AiTask
from models.chapter import Chapter
from controllers.config import ai_model_config_controller
from services.ai_task_executor import ai_task_executor
from services.nlp import RegexChapterRecognitionStrategy, NovelText
from utils.crud import CRUDBase
from models.novel import Novel
from schemas.novel import NovelCreate, NovelUpdate
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class NovelController(CRUDBase[Novel, NovelCreate, NovelUpdate]):
    def __init__(self):
        super().__init__(model=Novel)

    async def update(self, novel_id: int, obj_in: NovelUpdate) -> Novel:
        instance = await self.get(novel_id)
        return await super().update(instance, obj_in)

    async def patch(self, novel_id: int, obj_in: NovelUpdate) -> Novel:
        instance = await self.get(novel_id)
        return await super().patch(instance, obj_in)

    async def remove(self, novel_id: int) -> None:
        instance = await self.get(novel_id)
        await super().remove(instance)

    async def split(self, novel_id: int):
        """使用nlp拆分章节"""
        # 使用 NLP 服务识别章节
        novel = await self.get(novel_id)

        # 如果已经有章节了，禁止使用此方法
        if await novel.chapters:
            raise HTTPException(400, detail="已有章节，不支持分章。")

        novel_text = NovelText.from_string(novel.content)
        service = RegexChapterRecognitionStrategy()
        parsed_chapters = service.recognize(novel_text)

        # 如果没有识别到章节，默认整个小说作为一个章节
        if not parsed_chapters:
            parsed_chapters = [
                type(
                    "ParsedChapterResult",
                    (),
                    {
                        "title": "第一章",
                        "content": novel.content,
                        "start_index": 0,
                        "end_index": len(novel.content),
                        "confidence": 1.0,
                    },
                )()
            ]

        # 创建章节记录
        for idx, chapter_result in enumerate(parsed_chapters):
            await Chapter.create(
                novel_id=novel.id,
                number=idx + 1,
                name=chapter_result.title,
                content=chapter_result.content,
            )

        # 更新小说的总章节数和状态
        await novel.update_from_dict(
            {
                "total_chapters": len(parsed_chapters),
            }
        )
        await novel.save()
        return novel

    async def analyze(self, novel_id: int) -> AiTask:
        """提交 Agent 项目分析任务，模型密钥始终只从本地配置读取。"""
        novel = await self.get(novel_id)
        if not (novel.content or "").strip():
            raise HTTPException(status_code=400, detail="项目没有可分析的书稿内容")

        await ai_model_config_controller.get_active(AiTaskTypeEnum.extraction.value)
        await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image.value)
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.project_analysis)

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.project_analysis.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for task in active_tasks:
            if task.request_params.get("novel_id") == novel_id:
                return task

        return await ai_task_executor.submit(
            AiTaskTypeEnum.project_analysis,
            {"novel_id": novel_id, "resolution": "1K"},
        )

    async def latest_analysis(self, novel_id: int) -> AiTask | None:
        await self.get(novel_id)
        tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.project_analysis.value,
        ).order_by("-created_at")
        return next(
            (task for task in tasks if task.request_params.get("novel_id") == novel_id),
            None,
        )


novel_controller = NovelController()
