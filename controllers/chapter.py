from fastapi import HTTPException

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter_export import ChapterExport
from models.finished_episode import FinishedEpisodePublication
from models.video_edit import ChapterEditDraft
from models.scene import Scene
from models.video import Video
from services.creation_objects import project_write
from services.extraction.context import normalize_source_chapters
from utils.messages import localized_message
from controllers.config import general_config_controller
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from schemas.chapter import ChapterCreate, ChapterPatch, ChapterUpdate
from services.ai_task_executor import ai_task_executor
from services.chapter_titles import normalize_chapter_title
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class ChapterController(CRUDBase[Chapter, ChapterCreate, ChapterUpdate]):
    def __init__(self):
        super().__init__(model=Chapter)

    async def create(self, obj_in: ChapterCreate) -> Chapter:
        """创建章节并更新小说的 total_chapters。

        number 未传时，自动取该小说下最大 number + 1。
        """
        async with project_write(obj_in.novel_id) as db:
            chapters = Chapter.filter(novel_id=obj_in.novel_id).using_db(db)
            number = obj_in.number
            if number is None:
                last = await chapters.order_by("-number").first()
                number = last.number + 1 if last else 1
            elif await chapters.filter(number=number).exists():
                raise HTTPException(409, localized_message('集号已存在'))
            values = obj_in.model_dump(exclude_unset=True)
            values.update(number=number, name=normalize_chapter_title(obj_in.name))
            chapter = await Chapter.create(**values, using_db=db)
            await Novel.filter(id=obj_in.novel_id).using_db(db).update(episodes_managed=True, total_chapters=await chapters.count())
            return chapter

    async def _edit(self, chapter_id: int, obj_in: ChapterUpdate | ChapterPatch) -> Chapter:
        chapter = await self.get(chapter_id)
        async with project_write(chapter.novel_id):
            chapter = await self.get(chapter_id)
            values = obj_in.model_dump(exclude_unset=True)
            if values.pop('novel_id', chapter.novel_id) != chapter.novel_id:
                raise HTTPException(409, localized_message('集数只能在所属作品中编辑'))
            if 'number' in values and values['number'] is None:
                raise HTTPException(422, localized_message('集号不能为空'))
            if 'number' in values and values['number'] != chapter.number:
                await self._ensure_unreferenced(chapter)
                if await Chapter.filter(novel_id=chapter.novel_id, number=values['number']).exists():
                    raise HTTPException(409, localized_message('集号已存在'))
            if values.get('name') is not None:
                values['name'] = normalize_chapter_title(values['name'])
            return await super().patch(chapter, values)

    async def update(self, chapter_id: int, obj_in: ChapterUpdate) -> Chapter:
        return await self._edit(chapter_id, obj_in)

    async def patch(self, chapter_id: int, obj_in: ChapterPatch) -> Chapter:
        return await self._edit(chapter_id, obj_in)

    async def _ensure_unreferenced(self, chapter: Chapter) -> None:
        for task in await AiTask.filter(status__in=[TaskStatusEnum.pending, TaskStatusEnum.running, TaskStatusEnum.queued]):
            params = task.request_params or {}
            if params.get('novel_id') == chapter.novel_id and (params.get('chapter_id') == chapter.id or task.task_type in {AiTaskTypeEnum.project_analysis, AiTaskTypeEnum.creation_agent}):
                raise HTTPException(409, localized_message('本集仍有任务执行中'))
        # Assets store chapter numbers; scenes, videos and exports store database IDs.
        if (await Video.filter(scene__chapter_id=chapter.id).exists()
                or await ChapterExport.filter(chapter_id=chapter.id).exists()
                or await FinishedEpisodePublication.filter(chapter_id=chapter.id).exists()
                or await ChapterEditDraft.filter(chapter_id=chapter.id).exists()):
            raise HTTPException(409, localized_message('本集已有视频、成片或剪辑记录'))
        if await Scene.with_deleted().filter(chapter_id=chapter.id).exists():
            raise HTTPException(409, localized_message('本集已有分镜'))
        for query, field in ((Asset.with_deleted().filter(novel_id=chapter.novel_id), 'source_chapters'),
                             (AssetVariant.with_deleted().filter(asset__novel_id=chapter.novel_id), 'chapter_numbers')):
            groups = await query.values_list(field, flat=True)
            if any(chapter.number in normalize_source_chapters(group) for group in groups):
                raise HTTPException(409, localized_message('本集已关联资产或形态'))

    async def remove(self, chapter_id: int) -> None:
        chapter = await self.get(chapter_id)
        async with project_write(chapter.novel_id) as db:
            chapter = await self.get(chapter_id)
            await self._ensure_unreferenced(chapter)
            await chapter.delete(using_db=db)
            count = await Chapter.filter(novel_id=chapter.novel_id).using_db(db).count()
            await Novel.filter(id=chapter.novel_id).using_db(db).update(episodes_managed=True, total_chapters=count)

    async def extract(
        self, chapter_id: int, team_id: int | None = None, user_id: int | None = None, conversation_id: int | None = None,
        *, assistant_model_config_id: int | None = None,
    ) -> AiTask:
        """提交提取任务，返回任务记录供前端轮询。"""
        chapter = await self.get(chapter_id)

        # 1. 获取提取任务的启用配置（团队自定义优先，官方兜底）
        from services.creation_agent.skill_execution import require_agent
        config, _ = await require_agent(team_id, assistant_model_config_id)
        prompt_language = await general_config_controller.get_prompt_language()

        # 2. 先清理超时异常任务，再检查是否有活跃任务
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.extraction)

        # 3. 提交任务（BackgroundTask 中执行）
        request_params = {
            "chapter_id": chapter.id,
            "novel_id": chapter.novel_id,
            "assistant_model_config_id": config.id,
            "model_config_id": config.id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "concurrency": config.concurrency,
            "supports_json_output": config.supports_json_output,
            "max_context_characters": config.max_context_characters,
            "prompt_language": prompt_language,
        }
        if conversation_id is not None:
            request_params["conversation_id"] = conversation_id
        if team_id is not None:
            request_params["team_id"] = team_id
        if user_id is not None:
            request_params["user_id"] = user_id
        from services.creation_agent.skill_execution import prepare_workflow
        request_params = await prepare_workflow(request_params)
        from services.creation_objects import project_write
        async with project_write(chapter.novel_id) as connection:
            from services.creation_agent.submissions import previous_submission, bind_submission
            previous = await previous_submission(1, {**request_params, "team_id": team_id, "user_id": user_id}, connection)
            if previous:
                return previous
            for existing in await AiTask.filter(task_type=AiTaskTypeEnum.extraction.value, status__in=[1,2,6]).using_db(connection):
                if existing.request_params.get('chapter_id') == chapter_id:
                    if assistant_model_config_id is not None and existing.request_params.get("assistant_model_config_id") != assistant_model_config_id:
                        raise HTTPException(409, localized_message("请等待当前任务完成后再切换模型"))
                    return await bind_submission(existing, {**request_params, "team_id": team_id, "user_id": user_id})
            return await ai_task_executor.submit(AiTaskTypeEnum.extraction, request_params, db_connection=connection)


    async def latest_extraction_task(self, chapter_id: int) -> AiTask | None:
        """返回章节最近一次提取任务，用于页面恢复任务状态。"""
        await self.get(chapter_id)
        tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.extraction.value,
        ).order_by("-created_at")
        latest = next(
            (
                task
                for task in tasks
                if task.request_params.get("chapter_id") == chapter_id
            ),
            None,
        )
        from services.extraction.errors import describe_extraction_failure
        return await describe_extraction_failure(latest)


chapter_controller = ChapterController()
