import asyncio

from fastapi import HTTPException

from models.ai_task import AiTask
from models.chapter import Chapter
from controllers.config import ai_model_config_controller, general_config_controller
from services.ai_task_executor import ai_task_executor
from services.chapter_titles import normalize_chapter_title
from services.document import analyze_oss_document
from services.audio_references import audio_reference_accessible
from services.oss import oss
from services.project_config import validate_project_config
from services.nlp import (
    ChapterSplitError,
    RegexChapterRecognitionStrategy,
    NovelText,
    validate_chapter_split,
)
from utils.crud import CRUDBase
from models.novel import Novel
from models.audio_reference import AudioReference
from schemas.novel import NovelCreate, NovelPatch, NovelUpdate
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class NovelController(CRUDBase[Novel, NovelCreate, NovelUpdate]):
    async def meta(self, novel_id: int) -> dict:
        """轻量元信息：不返回书稿正文，节约流量。"""
        novel = await self.get(novel_id)
        return {
            "id": novel.id,
            "name": novel.name,
            "author": novel.author,
            "description": novel.description,
            "cover": novel.cover,
            "total_chapters": novel.total_chapters,
            "tags": novel.tags,
            "story_outline": novel.story_outline,
            "project_type": novel.project_type,
            "project_setting": novel.project_setting,
            "style_key": getattr(novel, "style_key", None),
            "workflow_kind": getattr(novel, "workflow_kind", "script"),
            "aspect_ratio": getattr(novel, "aspect_ratio", None),
            "resolution": getattr(novel, "resolution", None),
            "custom_style_prompt": getattr(novel, "custom_style_prompt", None),
            "video_model_config_id": getattr(novel, "video_model_config_id", None),
            "narrator_audio_reference_id": getattr(novel, "narrator_audio_reference_id", None),
            "content_length": len(novel.content or ""),
            "created_at": novel.created_at,
            "updated_at": novel.updated_at,
        }

    def __init__(self):
        super().__init__(model=Novel)

    async def create(
        self,
        obj_in: NovelCreate,
        team_id: int | None = None,
        created_by: int | None = None,
    ) -> Novel:
        """创建项目；AUTH_ENABLED 时由 API 层传入 team_id / created_by。

        OSS 直传后前端只回传 `source_key`：服务端经内网读取并解析正文，
        避免书稿正文经浏览器中转（也避免超大 JSON 请求体）。
        """
        data = obj_in.model_dump(exclude_unset=True)
        source_key = data.pop("source_key", None)
        source_filename = data.pop("source_filename", None) or "书稿.txt"
        if source_key:
            if not oss.enabled:
                raise HTTPException(status_code=400, detail="未启用对象存储")
            try:
                analysis = await analyze_oss_document(source_key, source_filename)
            except HTTPException:
                raise
            except Exception as error:  # 读取/解析失败统一转 400
                raise HTTPException(
                    status_code=400, detail=f"从对象存储读取书稿失败：{error}"
                ) from error
            text = (analysis["text_content"] or "").strip()
            if not text:
                raise HTTPException(
                    status_code=400,
                    detail="未能从上传文件读取正文，请转换为 TXT、MD、DOCX 或文本型 PDF 后重试",
                )
            validation = analysis["chapter_validation"]
            if validation and not validation["valid"]:
                raise HTTPException(status_code=422, detail=validation["message"])
            data["content"] = text
        data = validate_project_config(data)
        narrator_reference_id = data.get("narrator_audio_reference_id")
        if narrator_reference_id is not None:
            reference = await AudioReference.get_or_none(
                id=narrator_reference_id,
                is_active=True,
            )
            if reference is None or (
                not audio_reference_accessible(
                    reference,
                    team_id=team_id,
                    created_by=created_by,
                )
            ):
                raise HTTPException(400, detail="选择的旁白音色不存在或不可用")
        return await super().create(data, team_id=team_id, created_by=created_by)

    async def list(
        self,
        params,
        response_model,
        search_fields=None,
        team_id: int | None = None,
    ) -> dict:
        """项目列表；team_id 非空时仅返回本团队项目（超管传 None 看全部）。"""
        base_query = None
        if team_id is not None:
            base_query = Novel.filter(team_id=team_id)
        return await super().list(params, response_model, search_fields, base_query)

    async def update(self, novel_id: int, obj_in: NovelUpdate) -> Novel:
        instance = await self.get(novel_id)
        await self._validate_video_model_preference(instance, obj_in)
        await self._validate_narrator_audio_reference(instance, obj_in)
        data = validate_project_config(
            obj_in.model_dump(exclude_unset=True, exclude={"id"}),
            current=instance,
        )
        return await super().update(instance, data)

    async def patch(self, novel_id: int, obj_in: NovelPatch) -> Novel:
        instance = await self.get(novel_id)
        await self._validate_video_model_preference(instance, obj_in)
        await self._validate_narrator_audio_reference(instance, obj_in)
        data = validate_project_config(
            obj_in.model_dump(exclude_unset=True, exclude={"id"}),
            current=instance,
        )
        return await super().patch(instance, data)

    @staticmethod
    async def _validate_video_model_preference(
        instance: Novel,
        obj_in: NovelUpdate | NovelPatch,
    ) -> None:
        if (
            "video_model_config_id" in obj_in.model_fields_set
            and obj_in.video_model_config_id is not None
        ):
            await ai_model_config_controller.get_active(
                AiTaskTypeEnum.video.value,
                obj_in.video_model_config_id,
                team_id=instance.team_id,
            )

    @staticmethod
    async def _validate_narrator_audio_reference(
        instance: Novel,
        obj_in: NovelUpdate | NovelPatch,
    ) -> None:
        if "narrator_audio_reference_id" not in obj_in.model_fields_set:
            return
        reference_id = obj_in.narrator_audio_reference_id
        if reference_id is None:
            return
        reference = await AudioReference.get_or_none(id=reference_id, is_active=True)
        if reference is None:
            raise HTTPException(400, detail="选择的旁白音色不存在或已停用")
        if not audio_reference_accessible(
            reference,
            team_id=instance.team_id,
            created_by=instance.created_by,
        ):
            raise HTTPException(404, detail="选择的旁白音色不存在")

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

        # 章节识别 + 质量校验是 CPU 密集操作，放到线程池执行，
        # 避免在单 worker 的 uvicorn 事件循环里阻塞其他请求（如 /api/auth/status）。
        parsed_chapters = await asyncio.to_thread(
            self._parse_chapters, novel.content or ""
        )

        # 批量创建章节，避免上千章书稿逐条写库造成长时间等待。
        await Chapter.bulk_create([
            Chapter(
                novel_id=novel.id,
                number=idx + 1,
                name=normalize_chapter_title(
                    chapter_result.title,
                    fallback=novel.name,
                ),
                content=chapter_result.content,
            )
            for idx, chapter_result in enumerate(parsed_chapters)
        ])

        # 更新小说的总章节数和状态
        await novel.update_from_dict(
            {
                "total_chapters": len(parsed_chapters),
            }
        )
        await novel.save()
        return novel

    @staticmethod
    def _parse_chapters(content: str):
        """识别章节并做质量校验（纯 CPU，供线程池调用）。"""
        novel_text = NovelText.from_string(content)
        parsed_chapters = RegexChapterRecognitionStrategy().recognize(novel_text)

        try:
            validate_chapter_split(content, parsed_chapters)
        except ChapterSplitError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        # 短篇无章节标记时仍可作为单章；长篇会在上面的质量校验中被拒绝。
        if not parsed_chapters:
            parsed_chapters = [
                type(
                    "ParsedChapterResult",
                    (),
                    {
                        "title": "第一章",
                        "content": content,
                        "start_index": 0,
                        "end_index": len(content),
                        "confidence": 1.0,
                    },
                )()
            ]
        return parsed_chapters

    async def analyze(
        self,
        novel_id: int,
        team_id: int | None = None,
        user_id: int | None = None,
    ) -> AiTask:
        """提交 Agent 项目分析任务，模型密钥始终只从本地配置读取。"""
        novel = await self.get(novel_id)
        if not (novel.content or "").strip():
            raise HTTPException(status_code=400, detail="项目没有可分析的书稿内容")

        await ai_model_config_controller.get_active_with_legacy_fallback(
            AiTaskTypeEnum.project_analysis.value,
            AiTaskTypeEnum.extraction.value,
            team_id=team_id,
        )
        await ai_model_config_controller.get_active(
            AiTaskTypeEnum.reference_image.value, team_id=team_id
        )
        prompt_language = await general_config_controller.get_prompt_language()
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.project_analysis)

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.project_analysis.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for task in active_tasks:
            if task.request_params.get("novel_id") == novel_id:
                return task

        params = {
            "novel_id": novel_id,
            "resolution": "1K",
            "prompt_language": prompt_language,
        }
        if team_id is not None:
            params["team_id"] = team_id
        if user_id is not None:
            params["user_id"] = user_id
        return await ai_task_executor.submit(
            AiTaskTypeEnum.project_analysis,
            params,
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
