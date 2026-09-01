#!/usr/bin/env python3
"""为已有项目封面幂等生成 WebP 列表缩略图和详情预览图。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from tortoise import Tortoise

from config import settings
from main import tortoise_config
from models.novel import Novel
from services.cover_derivatives import (
    cover_derivative_reference,
    local_media_path,
    render_cover_derivatives,
    write_local_cover_derivatives,
)
from services.oss import normalize_media_url, oss


IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


async def backfill_cover_derivatives(
    novel_ids: list[int] | None = None,
) -> dict[str, int]:
    query = Novel.filter(cover__not_isnull=True).exclude(cover="")
    if novel_ids:
        query = query.filter(id__in=novel_ids)

    scanned = generated = skipped = failed = 0
    media_root = Path(settings.MEDIA_PATH)
    for novel in await query.order_by("id"):
        scanned += 1
        stored = normalize_media_url(novel.cover)
        try:
            if stored and stored.startswith("/media/"):
                source = local_media_path(media_root, stored)
                if source is None or not source.is_file():
                    raise FileNotFoundError("本地封面不存在")
                destinations = [
                    local_media_path(
                        media_root,
                        cover_derivative_reference(stored, kind),
                    )
                    for kind in ("thumbnail", "preview")
                ]
                if all(path and path.is_file() for path in destinations):
                    skipped += 1
                    continue
                image_bytes = await asyncio.to_thread(source.read_bytes)
                await asyncio.to_thread(
                    write_local_cover_derivatives,
                    media_root,
                    stored,
                    image_bytes,
                    force=False,
                )
            elif stored and oss.enabled and stored.startswith(("uploads/", "remake/")):
                image_bytes = await oss.get_bytes(stored)
                derivatives = await asyncio.to_thread(
                    render_cover_derivatives,
                    image_bytes,
                )
                for kind, data in derivatives.items():
                    key = cover_derivative_reference(stored, kind)
                    if key:
                        await oss.put_bytes(
                            key,
                            data,
                            "image/webp",
                            cache_control=IMMUTABLE_CACHE_CONTROL,
                        )
            else:
                skipped += 1
                continue
            generated += 1
        except Exception as error:
            failed += 1
            print(f"项目 {novel.id} 封面派生失败：{type(error).__name__}")

    return {
        "scanned": scanned,
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
    }


async def run(novel_ids: list[int] | None = None) -> None:
    await Tortoise.init(config=tortoise_config)
    try:
        stats = await backfill_cover_derivatives(novel_ids)
        print(
            "封面派生回填完成："
            f"扫描 {stats['scanned']}，生成 {stats['generated']}，"
            f"跳过 {stats['skipped']}，失败 {stats['failed']}"
        )
        if stats["failed"]:
            raise SystemExit(1)
    finally:
        await Tortoise.close_connections()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--novel-id",
        type=int,
        action="append",
        dest="novel_ids",
        help="只回填指定项目；可重复传入。默认处理全部项目。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    asyncio.run(run(arguments.novel_ids))
