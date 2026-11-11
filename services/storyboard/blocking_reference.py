"""Resolve a shot's actual overhead plan to a still image accepted by video providers."""
import asyncio
import hashlib
from pathlib import Path
import re
import sys
import subprocess
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET

from fastapi import HTTPException

from config import settings
from services.media_processing import remote_processing_enabled, run_media_async
from utils.messages import localized_message


BLOCKING_ID = "novelvids:blocking-map"


def has_drawable_plan(params):
    plan = (params or {}).get("blocking_map")
    return isinstance(plan, dict) and bool(plan) and (bool(plan.get("layout")) or len(params.get("segments") or []) > 1)


def blocking_source(scene_id, metadata, params):
    for item in (metadata.get("imported_media") or []) if isinstance(metadata, dict) else []:
        if isinstance(item, dict) and item.get("role") == "blocking" and isinstance(item.get("url"), str) and item["url"]:
            return item["url"]
    if has_drawable_plan(params):
        return f"/api/scene/{scene_id}/blocking-map.svg"


def standalone_svg(content: bytes) -> bytes:
    # Only self-contained vector art is passed to the platform's image decoder.
    if len(content) > 8_000_000 or b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError("Invalid SVG document")
    root = ET.fromstring(content)
    elements = {'svg', 'g', 'title', 'desc', 'defs', 'marker', 'clipPath', 'rect', 'circle',
                'ellipse', 'line', 'polyline', 'polygon', 'path', 'text', 'tspan',
                'linearGradient', 'radialGradient', 'stop'}
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] not in elements:
            raise ValueError("Unsupported diagram element")
        for key, value in node.attrib.items():
            if key.rsplit('}', 1)[-1] in {'href', 'base'} or key.startswith('on') or re.search(
                r'url\(\s*(?!#[\w.-]+\))|@import|\\', value, re.I
            ):
                raise ValueError("Unsupported diagram attribute")
    return ET.tostring(root, encoding="utf-8")


async def rasterize(vector: Path, image: Path):
    if sys.platform == "darwin" and not remote_processing_enabled():
        await asyncio.to_thread(subprocess.run,
            ["sips", "-s", "format", "png", str(vector), "--out", str(image)],
            check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        await run_media_async(["ffmpeg", "-y", "-i", str(vector), "-frames:v", "1", str(image)],
                              timeout=30, check=True)


async def provider_image(scene, source):
    if source == f"/api/scene/{scene.id}/blocking-map.svg":
        from schemas.scene import BlockingMap
        from prompts.skills.scripts.draw_blocking import draw
        plan = BlockingMap.model_validate(scene.prompt_params["blocking_map"])
        svg = draw(plan.model_dump(exclude_none=True)).encode()
    else:
        if not re.fullmatch(r"/media/work-packages/[0-9a-f]{64}\.(svg|png|jpe?g|webp)", source):
            raise HTTPException(422, localized_message("空间定位图来源无效"))
        path = Path(settings.MEDIA_PATH) / source.removeprefix("/media/")
        if not path.is_file():
            raise HTTPException(422, localized_message("空间定位图文件不存在"))
        if path.suffix != ".svg":
            return source
        svg = await asyncio.to_thread(path.read_bytes)
    key = hashlib.sha256(svg).hexdigest() + ".png"
    directory = Path(settings.MEDIA_PATH).resolve() / "blocking-maps"
    destination = directory / key
    if not destination.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=directory) as scratch:
            vector, image = Path(scratch) / "map.svg", Path(scratch) / "map.png"
            try:
                vector.write_bytes(standalone_svg(svg))
                await rasterize(vector, image)
                if not image.is_file() or not image.stat().st_size:
                    raise ValueError()
                image.replace(destination)
            except (OSError, ET.ParseError, ValueError, TimeoutError, subprocess.SubprocessError) as error:
                raise HTTPException(422, localized_message("空间定位图无法转为视频参考图，请提供 PNG 定位图")) from error
    return "/media/blocking-maps/" + key
