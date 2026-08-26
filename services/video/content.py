"""视频供应商共享的多模态 content 构建。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# 匹配 @{Name} 和 @Name（兼容旧格式）。
_ENTITY_RE = re.compile(r"@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)")
_MEDIA_REFERENCE_RE = re.compile(r"^(?:图|图片|视频|音频)\d+$")


@dataclass(frozen=True)
class PreparedVideoContent:
    """供应商无关的 content 及其引用计数。"""

    items: list[dict[str, Any]]
    prompt: str
    reference_image_count: int
    reference_video_count: int
    reference_audio_count: int


def process_subject_prompt(
    prompt: str,
    subjects: list[dict[str, Any]] | None,
    max_ref_images: int,
) -> tuple[str, list[str]]:
    """将 @资产转换为顺序图片引用，并收集对应参考图。"""
    subject_map: dict[str, dict[str, Any]] = {
        subject["name"]: subject for subject in subjects
    } if subjects else {}
    reference_images: list[str] = []
    name_to_index: dict[str, int] = {}

    for subject in subjects or []:
        if len(reference_images) >= max_ref_images:
            break
        images = subject.get("images", [])
        if images:
            name_to_index[subject["name"]] = len(reference_images) + 1
            remaining = max_ref_images - len(reference_images)
            reference_images.extend(images[:remaining])

    def replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        if _MEDIA_REFERENCE_RE.fullmatch(name):
            return match.group(0)
        subject = subject_map.get(name)
        if not subject:
            return name
        index = name_to_index.get(subject["name"])
        if index is not None:
            return f"[图{index}]"
        return subject.get("description") or subject["name"]

    return _ENTITY_RE.sub(replace, prompt), reference_images


def prepare_video_content(
    *,
    prompt: str,
    subjects: list[dict[str, Any]] | None,
    generation_mode: str,
    max_reference_images: int,
    first_frame_url: str | None = None,
    last_frame_url: str | None = None,
    reference_images: list[str] | None = None,
    reference_videos: list[str] | None = None,
    reference_audios: list[str] | None = None,
) -> PreparedVideoContent:
    """按统一内部参数生成 Seedance/MiniMax 共用的 content 结构。"""
    processed_prompt, asset_images = process_subject_prompt(
        prompt,
        subjects if generation_mode == "reference" else None,
        max_reference_images,
    )
    items: list[dict[str, Any]] = [{"type": "text", "text": processed_prompt}]

    if generation_mode == "keyframes":
        if first_frame_url:
            items.append({
                "type": "image_url",
                "image_url": {"url": first_frame_url},
                "role": "first_frame",
            })
        if last_frame_url:
            items.append({
                "type": "image_url",
                "image_url": {"url": last_frame_url},
                "role": "last_frame",
            })
        return PreparedVideoContent(
            items=items,
            prompt=processed_prompt,
            reference_image_count=sum(item["type"] == "image_url" for item in items),
            reference_video_count=0,
            reference_audio_count=0,
        )

    deduplicated_images = list(dict.fromkeys([*asset_images, *(reference_images or [])]))
    deduplicated_videos = list(dict.fromkeys(reference_videos or []))
    deduplicated_audios = list(dict.fromkeys(reference_audios or []))
    for image in deduplicated_images:
        items.append({
            "type": "image_url",
            "image_url": {"url": image},
            "role": "reference_image",
        })
    for video in deduplicated_videos:
        items.append({
            "type": "video_url",
            "video_url": {"url": video},
            "role": "reference_video",
        })
    for audio in deduplicated_audios:
        items.append({
            "type": "audio_url",
            "audio_url": {"url": audio},
            "role": "reference_audio",
        })
    return PreparedVideoContent(
        items=items,
        prompt=processed_prompt,
        reference_image_count=len(deduplicated_images),
        reference_video_count=len(deduplicated_videos),
        reference_audio_count=len(deduplicated_audios),
    )
