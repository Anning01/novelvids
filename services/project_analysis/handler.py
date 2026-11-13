
from utils.messages import localized_message
import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from config import settings
from controllers.config import ai_model_config_controller
from controllers.novel import novel_controller
from models.ai_task import AiTask
from models.chapter import Chapter
from models.novel import Novel
from prompts.project_analysis import render_analysis_messages, render_cover_prompt
from services.ai_task_executor import BaseTaskHandler
from services.chapter_titles import strip_chapter_ordinal
from services.project_analysis.results import cover_warning
from services.cover_derivatives import (
    cover_derivative_reference,
    render_cover_derivatives,
    write_local_cover_derivatives,
)
from services.image_generation import generate_images
from services.image_generation.capabilities import validate_selection
from services.llm.json_output import create_json_completion, completion_usage
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.prompt_language import normalize_prompt_language

logger = logging.getLogger(__name__)

MAX_ANALYSIS_TEXT_LENGTH = 8_000
MAX_SAMPLE_CHAPTERS = 8


class KeyCharacter(BaseModel):
    name: str = Field(description="人物标准名称")
    aliases: list[str] = Field(default_factory=list, description="人物别名")
    role: str = Field(description="人物在故事中的身份和作用")
    description: str = Field(description="用一句话概括人物在选段中的关键行动")
    # Retain old analysis payloads without asking the model for visual assets.
    base_traits: SkipJsonSchema[str] = ''
    chapter_numbers: list[int] = Field(default_factory=list, description="人物出现的章节序号")


class BookAnalysis(BaseModel):
    book_types: list[str] = Field(description="一至三个简短的题材标签")
    story_outline: str = Field(description="用一个短段落概括已读正文中的主线和转折")
    key_characters: list[KeyCharacter] = Field(description="对理解主线必要的人物，通常一至四位，按材料取舍")


def _build_analysis_material(
    novel: Novel, chapters: list[Chapter], language: str = "zh"
) -> str:
    """优先使用完整书稿；超长时按章节均匀取样，避免只分析故事开头。"""
    content = (novel.content or "").strip()
    if content and len(content) <= MAX_ANALYSIS_TEXT_LENGTH:
        return content

    if not chapters:
        if not content:
            return ""
        head = content[: MAX_ANALYSIS_TEXT_LENGTH // 2]
        tail = content[-MAX_ANALYSIS_TEXT_LENGTH // 2 :]
        return json.dumps({"head": head, "tail": tail}, ensure_ascii=False)

    allowance = MAX_ANALYSIS_TEXT_LENGTH // len(chapters)
    blocks = []
    for chapter in chapters:
        chapter_text = chapter.production_text.strip()
        if not chapter_text:
            continue
        if len(chapter_text) > allowance:
            first = allowance * 2 // 3
            chapter_text = f"{chapter_text[:first]}\n……\n{chapter_text[-(allowance - first):]}"
        chapter_title = strip_chapter_ordinal(chapter.name)
        block = json.dumps({"chapter_number": chapter.number, "title": chapter_title,
                            "content": chapter_text}, ensure_ascii=False)
        blocks.append(block)
    return "\n\n".join(blocks)


async def _save_cover(image: Any, novel_id: int) -> str:
    remote_url = getattr(image, "url", None)
    b64_json = getattr(image, "b64_json", None)
    suffix = ".png"
    image_bytes: bytes

    if remote_url:
        parsed_suffix = os.path.splitext(urlparse(remote_url).path)[1].lower()
        if parsed_suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = parsed_suffix
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(remote_url)
            response.raise_for_status()
            image_bytes = response.content
    elif b64_json:
        image_bytes = base64.b64decode(b64_json)
    else:
        raise ValueError(localized_message('生图模型未返回可用的封面图片'))

    filename = f"novel-{novel_id}-{uuid4().hex}{suffix}"
    from services.oss import make_upload_key, oss

    if oss.enabled and not getattr(image, "keep_local", False):
        derivatives = await asyncio.to_thread(render_cover_derivatives, image_bytes)
        key = make_upload_key(None, filename)
        await oss.put_bytes(key, image_bytes, _cover_content_type(suffix))
        for kind, derivative_bytes in derivatives.items():
            derivative_key = cover_derivative_reference(key, kind)
            if derivative_key:
                await oss.put_bytes(
                    derivative_key,
                    derivative_bytes,
                    "image/webp",
                    cache_control="public, max-age=31536000, immutable",
                )
        # 落库存 key，读取时再由 resolve_media_url 重新签发临时 URL
        return key

    cover_dir = Path(settings.MEDIA_PATH) / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)
    local_path = cover_dir / filename
    temporary = local_path.with_suffix(local_path.suffix + ".tmp")
    temporary.write_bytes(image_bytes)
    temporary.replace(local_path)
    reference = f"/media/covers/{filename}"
    await asyncio.to_thread(
        write_local_cover_derivatives,
        Path(settings.MEDIA_PATH),
        reference,
        image_bytes,
    )
    return reference


def _cover_content_type(extension: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(extension.lower(), "application/octet-stream")


class ProjectAnalysisTaskHandler(BaseTaskHandler):
    """完成分章与书稿理解；人物仅保留为分析参考，封面按请求生成。"""

    async def execute(self, request_params: dict) -> dict:
        novel_id = int(request_params["novel_id"])
        prompt_language = normalize_prompt_language(request_params.get("prompt_language"))
        from services.ai_task_executor import current_task_id
        task_id = request_params.get("task_id") or current_task_id.get()

        async def stopped():
            if not task_id:
                return False
            return not await AiTask.filter(id=task_id, status=TaskStatusEnum.running.value).exists()

        if await stopped():
            raise ValueError(localized_message('任务已取消或结束'))
        novel = await Novel.get(id=novel_id)
        if request_params.get("operation") == "project_cover":
            if not request_params.get("cover_model_config_id"):
                raise ValueError(localized_message("请选择生图模型"))
            return await self._generate_cover(
                novel, request_params, prompt_language, task_id,
                outline=novel.story_outline or novel.description or "",
                book_types=novel.tags or [], result={}, stopped=stopped,
            )
        chapter_query = Chapter.filter(novel_id=novel_id).order_by("number")
        chapter_count = await chapter_query.count()
        if not chapter_count and not novel.episodes_managed:
            await novel_controller.split(novel_id)
            chapter_count = await chapter_query.count()

        samples = []
        if (not (novel.content or "").strip() or len(novel.content or "") > MAX_ANALYSIS_TEXT_LENGTH) and chapter_count:
            numbers = await chapter_query.values_list("number", flat=True)
            if len(numbers) > MAX_SAMPLE_CHAPTERS:
                last = len(numbers) - 1
                numbers = [numbers[round(i * last / (MAX_SAMPLE_CHAPTERS - 1))] for i in range(MAX_SAMPLE_CHAPTERS)]
            samples = await chapter_query.filter(number__in=numbers).only("number", "name", "content", "screenplay")
        material = _build_analysis_material(novel, samples, prompt_language)
        if not material.strip():
            raise ValueError(localized_message('项目没有可分析的书稿内容'))

        from services.creation_agent.skill_execution import current_execution, require_agent
        execution = current_execution.get()
        if execution:
            llm_config, _ = await require_agent(request_params.get('team_id'), request_params['assistant_model_config_id'])
            analysis = await execution.generate('story', {'name': novel.name, 'manuscript': material,
                'chapter_count': chapter_count}, BookAnalysis)
            token_usage = {}
        else:
            llm_config = await ai_model_config_controller.get_active_with_legacy_fallback(
                AiTaskTypeEnum.project_analysis.value,
                AiTaskTypeEnum.extraction.value,
                team_id=request_params.get("team_id"),
            )

            if await stopped():
                raise ValueError(localized_message('任务已取消或结束'))
            llm_client = AsyncOpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)
            analysis, completion = await create_json_completion(
                llm_client,
                model=llm_config.model,
                messages=render_analysis_messages(name=novel.name, chapter_count=chapter_count, material=material, prompt_language=prompt_language),
                response_model=BookAnalysis,
                prompt_language=prompt_language,
                supports_json_output=llm_config.supports_json_output,
            )
            token_usage = completion_usage(completion)

        result = {
            **analysis.model_dump(), 'analysis_completed': False,
            'cover_status': 'ready' if novel.cover else 'not_requested', 'chapter_count': chapter_count, 'cover': novel.cover,
            'token_usage': token_usage, 'llm_config_id': llm_config.id, 'llm_model': llm_config.model,
        }
        if await stopped():
            result['cover_status'] = 'cancelled'
            return result

        async def persist_analysis():
            from services.creation_objects import project_write
            async with project_write(novel_id):
                novel.total_chapters = await Chapter.filter(novel_id=novel_id).count()
                novel.tags = analysis.book_types
                novel.story_outline = analysis.story_outline
                await novel.save(update_fields=["total_chapters", "tags", "story_outline", "updated_at"])
            return {"novel_id": novel_id}

        if execution:
            from services.creation_agent.operation_receipts import execute_step
            await execute_step(execution.params["task_id"], "persist:story", persist_analysis, atomic=True)
        else:
            await persist_analysis()
        result['analysis_completed'] = True
        if await stopped():
            result['cover_status'] = 'cancelled'
            return result
        cover_model_config_id = request_params.get("cover_model_config_id")
        if not cover_model_config_id or not request_params.get("include_cover", True):
            return result
        return await self._generate_cover(
            novel, request_params, prompt_language, task_id,
            outline=analysis.story_outline, book_types=analysis.book_types, result=result, stopped=stopped,
        )

    async def _generate_cover(self, novel, request_params, prompt_language, task_id, *, outline, book_types, result, stopped):
        from services.creation_agent.skill_execution import current_execution

        execution = current_execution.get()
        cover_model_config_id = request_params["cover_model_config_id"]
        if task_id:
            await AiTask.filter(id=task_id, status=TaskStatusEnum.running.value).update(
                response_data={**result, "cover_status": "pending"}
            )
        try:
            image_config = await ai_model_config_controller.get_active(
                AiTaskTypeEnum.reference_image.value, cover_model_config_id, team_id=request_params.get("team_id"),
            )
            cover_ratio = novel.aspect_ratio or "2:3"
            cover_selection = validate_selection(
                image_config.image_model_type, clarity=None, aspect_ratio=cover_ratio,
                output_format="png", generation_count=1,
            )
            if execution:
                from schemas.agent_workflow import CompletePrompt
                cover = await execution.generate('image', {'purpose': 'project_cover', 'name': novel.name,
                    'outline': outline, 'aspect_ratio': cover_ratio}, CompletePrompt)
                cover_prompt = cover.prompt
            else:
                cover_prompt = render_cover_prompt(name=novel.name, book_types=book_types,
                    story_outline=outline, prompt_language=prompt_language, aspect_ratio=cover_ratio)
            async def generate_cover():
                if await stopped():
                    result['cover_status'] = 'cancelled'
                    return {'cover_status': 'cancelled'}
                if execution:
                    await execution.before_request()
                images = await generate_images(
                    base_url=image_config.base_url, api_key=image_config.api_key, model=image_config.model,
                    prompt=cover_prompt,
                    api_protocol=image_config.api_protocol, resolution=cover_selection.provider_size,
                    aspect_ratio=cover_selection.aspect_ratio, output_format=cover_selection.output_format,
                    quality=cover_selection.provider_quality, count=1,
                    **({'timeout': None} if execution else {}),
                )
                # Preserve actual provider usage even if saving a returned image subsequently fails.
                result.update(image_usage={"image_count": len(images), "clarity": cover_selection.clarity},
                              image_config_id=image_config.id, image_model=image_config.model)
                cover = await _save_cover(images[0], novel.id)
                novel.cover = cover
                await novel.save(update_fields=["cover", "updated_at"])
                result["cover"] = cover
                result["cover_status"] = "ready"
                return {key: result[key] for key in ('cover', 'cover_status', 'image_usage', 'image_config_id', 'image_model') if key in result}
            if execution:
                from services.creation_agent.operation_receipts import execute_step
                result.update(await execute_step(execution.params['task_id'], 'media:cover', generate_cover, external=True))
            else:
                await generate_cover()
        except Exception as error:
            result.update(cover_status="failed", cover_warning=cover_warning(prompt_language))
            from services.image_generation import ImageGenerationError
            if isinstance(error, ImageGenerationError):
                result["cover_error"] = str(error)
            if execution:
                from models.agent_operation import AgentOperation
                if await AgentOperation.filter(task_id=execution.params['task_id'], external=True, state='uncertain').exists():
                    result["cover_status"] = "needs_review"
                    error.partial_result = result
                    raise
            logger.warning("Optional project cover failed: %s", type(error).__name__)
        return result
