import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from config import settings
from controllers.config import ai_model_config_controller
from controllers.novel import novel_controller
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from prompts.extraction import (
    SINGLE_CHARACTER_TRAIT_LABELS,
    ensure_ordered_trait_labels,
)
from prompts.reference import render_default_asset_prompt
from prompts.project_analysis import render_analysis_messages, render_cover_prompt
from services.ai_task_executor import BaseTaskHandler
from services.chapter_titles import strip_chapter_ordinal
from services.cover_derivatives import (
    cover_derivative_reference,
    render_cover_derivatives,
    write_local_cover_derivatives,
)
from services.image_generation import generate_images
from services.image_generation.capabilities import validate_selection
from services.llm.json_output import create_json_completion, completion_usage
from utils.enums import AiTaskTypeEnum, AssetTypeEnum, ImageSourceEnum
from utils.prompt_language import normalize_prompt_language

logger = logging.getLogger(__name__)

MAX_ANALYSIS_TEXT_LENGTH = 55_000


class KeyCharacter(BaseModel):
    name: str = Field(description="人物标准名称")
    aliases: list[str] = Field(default_factory=list, description="人物别名")
    role: str = Field(description="人物在故事中的身份和作用")
    description: str = Field(description="人物性格、背景、动机与人物弧光的中文概述")
    base_traits: str = Field(description="按任务指定语言撰写的详细人物外观描述")
    chapter_numbers: list[int] = Field(default_factory=list, description="人物出现的章节序号")

    @field_validator("base_traits")
    @classmethod
    def validate_base_traits(cls, value: str) -> str:
        return ensure_ordered_trait_labels(
            value,
            SINGLE_CHARACTER_TRAIT_LABELS,
            "关键人物视觉描述",
        )


class BookAnalysis(BaseModel):
    book_types: list[str] = Field(description="3 至 6 个准确、简短的中文题材或类型标签")
    story_outline: str = Field(description="完整故事大纲，包含主线冲突、关键转折和结局走向")
    key_characters: list[KeyCharacter] = Field(description="推动主线的关键人物，通常为 3 至 10 位")


def _build_analysis_material(novel: Novel, chapters: list[Chapter]) -> str:
    """优先使用完整书稿；超长时按章节均匀取样，避免只分析故事开头。"""
    content = (novel.content or "").strip()
    if len(content) <= MAX_ANALYSIS_TEXT_LENGTH:
        return content

    if not chapters:
        head = content[: MAX_ANALYSIS_TEXT_LENGTH // 2]
        tail = content[-MAX_ANALYSIS_TEXT_LENGTH // 2 :]
        return f"【书稿开头】\n{head}\n\n【书稿结尾】\n{tail}"

    sample_count = min(len(chapters), 24)
    if sample_count == 1:
        sampled_chapters = [chapters[0]]
    else:
        sample_indexes = {
            round(index * (len(chapters) - 1) / (sample_count - 1))
            for index in range(sample_count)
        }
        sampled_chapters = [chapters[index] for index in sorted(sample_indexes)]
    per_chapter = max(1, MAX_ANALYSIS_TEXT_LENGTH // len(sampled_chapters))
    blocks: list[str] = []
    used = 0
    for chapter in sampled_chapters:
        remaining = MAX_ANALYSIS_TEXT_LENGTH - used
        if remaining <= 0:
            break
        chapter_text = (chapter.content or "").strip()
        allowance = min(per_chapter, remaining)
        if len(chapter_text) > allowance:
            first = allowance * 2 // 3
            chapter_text = f"{chapter_text[:first]}\n……\n{chapter_text[-(allowance - first):]}"
        chapter_title = strip_chapter_ordinal(chapter.name)
        heading = f"第 {chapter.number} 章"
        if chapter_title:
            heading = f"{heading}：{chapter_title}"
        block = f"【{heading}】\n{chapter_text}"
        blocks.append(block)
        used += len(block)
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
        raise ValueError("生图模型未返回可用的封面图片")

    filename = f"novel-{novel_id}-{uuid4().hex}{suffix}"
    from services.oss import make_upload_key, oss

    if oss.enabled:
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


async def _sync_character_assets(
    novel: Novel,
    characters: list[KeyCharacter],
    chapter_count: int,
    prompt_language: str,
) -> None:
    for character in characters:
        name = character.name.strip()
        if not name:
            continue
        chapter_numbers = sorted(
            {number for number in character.chapter_numbers if 1 <= number <= chapter_count}
        )
        asset = await Asset.get_or_none(
            novel_id=novel.id,
            asset_type=AssetTypeEnum.person.value,
            canonical_name=name,
        )
        values = {
            "aliases": character.aliases,
            "description": character.description,
            "base_traits": render_default_asset_prompt(
                asset_type="person",
                visual_traits=character.base_traits,
                prompt_language=prompt_language,
            ),
            "is_global": False,
            "source_chapters": chapter_numbers,
            # 项目分析只建立全书人物档案，不代表某一章的增量提取版本。
            "last_updated_chapter": 0,
            "metadata": {
                "role": character.role,
                "analysis_source": "project_analysis",
                "reference_layout": "character_turnaround",
            },
        }
        if asset is None:
            await Asset.create(
                novel_id=novel.id,
                asset_type=AssetTypeEnum.person.value,
                canonical_name=name,
                image_source=ImageSourceEnum.ai.value,
                **values,
            )
        else:
            asset.update_from_dict(values)
            await asset.save()


class ProjectAnalysisTaskHandler(BaseTaskHandler):
    """完成 Agent 项目的分章、书稿理解、人物入库与 1K 封面生成。"""

    async def execute(self, request_params: dict) -> dict:
        novel_id = int(request_params["novel_id"])
        prompt_language = normalize_prompt_language(request_params.get("prompt_language"))
        novel = await Novel.get(id=novel_id)
        if not (novel.content or "").strip():
            raise ValueError("项目没有可分析的书稿内容")

        chapters = await Chapter.filter(novel_id=novel_id).order_by("number")
        if not chapters:
            await novel_controller.split(novel_id)
            chapters = await Chapter.filter(novel_id=novel_id).order_by("number")

        llm_config = await ai_model_config_controller.get_active_with_legacy_fallback(
            AiTaskTypeEnum.project_analysis.value,
            AiTaskTypeEnum.extraction.value,
            team_id=request_params.get("team_id"),
        )

        material = _build_analysis_material(novel, chapters)
        llm_client = AsyncOpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)
        analysis, completion = await create_json_completion(
            llm_client,
            model=llm_config.model,
            messages=render_analysis_messages(name=novel.name, chapter_count=len(chapters), material=material, prompt_language=prompt_language),
            response_model=BookAnalysis,
            supports_json_output=llm_config.supports_json_output,
        )
        token_usage = completion_usage(completion)

        await _sync_character_assets(
            novel,
            analysis.key_characters,
            len(chapters),
            prompt_language,
        )

        # Save the useful story result before the optional cover request.
        novel.total_chapters = len(chapters)
        novel.tags = analysis.book_types
        novel.story_outline = analysis.story_outline
        await novel.save(update_fields=["total_chapters", "tags", "story_outline", "updated_at"])
        result = {
            **analysis.model_dump(),
            "chapter_count": len(chapters),
            "cover": novel.cover,
            "token_usage": token_usage,
            "llm_config_id": llm_config.id,
            "llm_model": llm_config.model,
        }
        try:
            image_config = await ai_model_config_controller.get_active(
                AiTaskTypeEnum.reference_image.value, team_id=request_params.get("team_id"),
            )
            cover_selection = validate_selection(
                image_config.image_model_type, clarity=None, aspect_ratio="2:3",
                output_format="png", generation_count=1,
            )
            images = await generate_images(
                base_url=image_config.base_url, api_key=image_config.api_key, model=image_config.model,
                prompt=render_cover_prompt(name=novel.name, book_types=analysis.book_types,
                                           story_outline=analysis.story_outline, prompt_language=prompt_language),
                api_protocol=image_config.api_protocol, resolution=cover_selection.provider_size,
                aspect_ratio=cover_selection.aspect_ratio, output_format=cover_selection.output_format,
                quality=cover_selection.provider_quality, count=1,
            )
            # Preserve actual provider usage even if saving a returned image subsequently fails.
            result.update(image_usage={"image_count": len(images), "clarity": cover_selection.clarity},
                          image_config_id=image_config.id, image_model=image_config.model)
            cover = await _save_cover(images[0], novel_id)
            novel.cover = cover
            await novel.save(update_fields=["cover", "updated_at"])
            result["cover"] = cover
        except Exception as error:
            logger.warning("Optional project cover failed: %s", type(error).__name__)
            result["cover_warning"] = "故事分析已完成，封面暂未生成。可以继续提取资产和制作分镜；请在模型设置中检查图片服务后再试。"
        return result
