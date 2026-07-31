import base64
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from config import settings
from controllers.config import ai_model_config_controller
from controllers.novel import novel_controller
from models.asset import Asset
from models.chapter import Chapter
from models.novel import Novel
from services.ai_task_executor import BaseTaskHandler
from services.llm.json_output import create_json_completion
from utils.enums import AiTaskTypeEnum, AssetTypeEnum, ImageSourceEnum
from utils.prompt_language import normalize_prompt_language, prompt_language_name

logger = logging.getLogger(__name__)

MAX_ANALYSIS_TEXT_LENGTH = 55_000


class KeyCharacter(BaseModel):
    name: str = Field(description="人物标准名称")
    aliases: list[str] = Field(default_factory=list, description="人物别名")
    role: str = Field(description="人物在故事中的身份和作用")
    description: str = Field(description="人物性格、背景、动机与人物弧光的中文概述")
    base_traits: str = Field(description="按任务指定语言撰写的详细人物外观描述")
    chapter_numbers: list[int] = Field(default_factory=list, description="人物出现的章节序号")


class BookAnalysis(BaseModel):
    book_types: list[str] = Field(description="3 至 6 个准确、简短的中文题材或类型标签")
    story_outline: str = Field(description="完整故事大纲，包含主线冲突、关键转折和结局走向")
    key_characters: list[KeyCharacter] = Field(description="推动主线的关键人物，通常为 3 至 10 位")


ANALYSIS_SYSTEM_PROMPT = """你是一名资深影视开发编辑。请严格依据给定书稿完成结构化分析，不要虚构书稿中不存在的信息。
类型标签应简洁准确；故事大纲应覆盖开端、主要冲突、关键转折和结局走向；关键人物只保留真正推动主线的人物。
人物的 chapter_numbers 必须使用材料中给出的章节序号。base_traits 必须使用任务指定的提示词语言，描述可见且相对稳定的外貌、服装和气质，便于后续生图。"""


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
        block = f"【第 {chapter.number} 章：{chapter.name}】\n{chapter_text}"
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _cover_prompt(novel: Novel, analysis: BookAnalysis, prompt_language: str = "en") -> str:
    types = "、".join(analysis.book_types)
    if normalize_prompt_language(prompt_language) == "en":
        return f"""Create a vertical cinematic short-drama cover key visual for the novel "{novel.name}".
Genres: {types}.
Story outline: {analysis.story_outline}
Requirements: center the story's core conflict and atmosphere with cinematic composition and lighting; use a clear visual focal point suitable for a 2:3 vertical cover; do not include any text, title, subtitle, logo, watermark, or border; avoid distorted faces and extra limbs. Output at approximately 1K resolution."""
    return f"""为小说《{novel.name}》创作一张竖版影视短剧封面主视觉。
题材：{types}。
故事大纲：{analysis.story_outline}
要求：以故事核心冲突和氛围为主体，电影级构图与光影，视觉焦点明确，适合 2:3 竖版封面；画面中不要出现任何文字、标题、字幕、Logo、水印或边框；避免人物面部畸变和多余肢体。输出约 1K 分辨率。"""


async def _save_cover(image: Any, novel_id: int) -> str:
    cover_dir = Path(settings.MEDIA_PATH) / "covers"
    cover_dir.mkdir(parents=True, exist_ok=True)

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
    local_path = cover_dir / filename
    local_path.write_bytes(image_bytes)
    return f"/media/covers/{filename}"


async def _sync_character_assets(novel: Novel, characters: list[KeyCharacter], chapter_count: int) -> None:
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
            "base_traits": character.base_traits,
            "is_global": False,
            "source_chapters": chapter_numbers,
            "last_updated_chapter": max(chapter_numbers, default=0),
            "metadata": {"role": character.role, "analysis_source": "project_analysis"},
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

        llm_config = await ai_model_config_controller.get_active(AiTaskTypeEnum.extraction.value)
        image_config = await ai_model_config_controller.get_active(AiTaskTypeEnum.reference_image.value)

        material = _build_analysis_material(novel, chapters)
        llm_client = AsyncOpenAI(api_key=llm_config.api_key, base_url=llm_config.base_url)
        analysis, _ = await create_json_completion(
            llm_client,
            model=llm_config.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{ANALYSIS_SYSTEM_PROMPT}\n"
                        f"本任务的提示词语言是{prompt_language_name(prompt_language)}；"
                        "base_traits 必须严格使用该语言。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"书名：《{novel.name}》\n共 {len(chapters)} 章。\n\n以下是书稿材料：\n{material}",
                },
            ],
            response_model=BookAnalysis,
            supports_json_output=llm_config.supports_json_output,
        )

        await _sync_character_assets(novel, analysis.key_characters, len(chapters))

        image_client = AsyncOpenAI(api_key=image_config.api_key, base_url=image_config.base_url)
        image_response = await image_client.images.generate(
            model=image_config.model,
            prompt=_cover_prompt(novel, analysis, prompt_language),
            size="1K",
            response_format="url",
            n=1,
            extra_body={"watermark": False},
        )
        if not image_response.data:
            raise ValueError("生图模型未返回封面")
        cover = await _save_cover(image_response.data[0], novel_id)

        novel.cover = cover
        novel.total_chapters = len(chapters)
        await novel.save(update_fields=["cover", "total_chapters", "updated_at"])

        return {
            **analysis.model_dump(),
            "chapter_count": len(chapters),
            "cover": cover,
        }
