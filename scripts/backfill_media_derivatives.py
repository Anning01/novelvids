#!/usr/bin/env python3
"""为历史封面、设定资产图片和生成视频幂等补齐轻量预览。"""

from __future__ import annotations

import asyncio
from typing import Any

from tortoise import Tortoise

from main import tortoise_config
from models.ai_task import AiTask
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.novel import Novel
from models.video import Video
from services.cover_derivatives import ensure_image_derivatives
from services.video.poster import video_poster_service
from utils.enums import TaskStatusEnum


def _strings(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _strings(child)]
    return []


async def backfill_media_derivatives() -> dict[str, int]:
    image_references: set[str] = set()
    for novel in await Novel.exclude(cover__isnull=True).exclude(cover=""):
        if novel.cover:
            image_references.add(novel.cover)
    for asset in await Asset.all():
        image_references.update(
            value
            for value in (asset.main_image, asset.angle_image_1, asset.angle_image_2)
            if value
        )
        metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
        image_references.update(_strings(metadata.get("image_gallery")))
    for variant in await AssetVariant.all():
        image_references.update(_strings(variant.images))
    for task in await AiTask.all():
        response = task.response_data if isinstance(task.response_data, dict) else {}
        image_references.update(_strings(response.get("images")))

    stats = {
        "images_scanned": len(image_references),
        "images_generated": 0,
        "images_failed": 0,
        "videos_scanned": 0,
        "videos_generated": 0,
        "videos_failed": 0,
    }
    for reference in sorted(image_references):
        try:
            generated = await ensure_image_derivatives(reference)
            if generated:
                stats["images_generated"] += 1
        except Exception as error:
            stats["images_failed"] += 1
            print(f"图片派生失败：{type(error).__name__}")

    videos = await Video.filter(
        status=TaskStatusEnum.completed.value,
        url__not_isnull=True,
    ).exclude(url="")
    stats["videos_scanned"] = len(videos)
    for video in videos:
        metadata = video.metadata if isinstance(video.metadata, dict) else {}
        if metadata.get("poster_url") and metadata.get("poster_thumbnail_url"):
            continue
        try:
            posters = await video_poster_service.extract_and_store(
                str(video.url),
                video.id,
            )
            video.metadata = {**metadata, **posters}
            await video.save(update_fields=["metadata", "updated_at"])
            stats["videos_generated"] += 1
        except Exception as error:
            stats["videos_failed"] += 1
            print(f"视频 {video.id} 海报生成失败：{type(error).__name__}")
    return stats


async def run() -> None:
    await Tortoise.init(config=tortoise_config)
    try:
        stats = await backfill_media_derivatives()
        print(
            "媒体派生回填完成："
            f"图片 {stats['images_generated']}/{stats['images_scanned']}，"
            f"视频 {stats['videos_generated']}/{stats['videos_scanned']}，"
            f"失败 {stats['images_failed'] + stats['videos_failed']}"
        )
        if stats["images_failed"] or stats["videos_failed"]:
            raise SystemExit(1)
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(run())
