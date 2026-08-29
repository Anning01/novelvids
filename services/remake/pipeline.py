"""重制视频全局资产与逐镜头专业 Prompt 拆解流水线。"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompts.remake import ASSET_PROMPT, ASSET_SCHEMA, PROMPT_SCHEMA, PROMPT_TEMPLATE
from services.remake.gateway import MAX_MODEL_VIDEO_BYTES, RemakeVideoAnalysisGateway
from services.remake.media_prepare import prepare_video_for_model_input
from services.remake.prompt_render import (
    compact_catalog,
    normalize_global_assets,
    render_professional_prompt,
)
from services.remake.scene_detection import SceneDetector, scene_detector


class RemakePipelineError(RuntimeError):
    pass


ProgressCallback = Callable[[int, str], Awaitable[None]]


@dataclass(frozen=True)
class RemakePipelineResult:
    assets: dict[str, list[dict[str, Any]]]
    prompt_document: dict[str, list[dict[str, Any]]]
    metadata: dict[str, Any]
    token_usage: dict[str, int]


class RemakeDecompositionPipeline:
    def __init__(
        self,
        *,
        scene_detector: SceneDetector = scene_detector,
        gateway_factory: Callable[[Any], RemakeVideoAnalysisGateway] = RemakeVideoAnalysisGateway,
        prepare_video: Callable[..., Path] = prepare_video_for_model_input,
        probe_duration: Callable[[Path], float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.scene_detector = scene_detector
        self.gateway_factory = gateway_factory
        self.prepare_video = prepare_video
        self.probe_duration = probe_duration or _probe_media_duration
        self.clock = clock

    async def run(
        self,
        *,
        source_path: Path,
        model_config: Any,
        work_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> RemakePipelineResult:
        pipeline_started_at = self.clock()
        if not source_path.is_file():
            raise RemakePipelineError("来源视频不存在")
        work_dir.mkdir(parents=True, exist_ok=True)
        await _report(progress, 10, "preparing")
        model_source_path = await asyncio.to_thread(
            self.prepare_video,
            source_path,
            work_dir / "model-input",
            max_bytes=MAX_MODEL_VIDEO_BYTES,
        )

        gateway = self.gateway_factory(model_config)
        await _report(progress, 20, "extracting_assets")
        raw_assets = await gateway.analyze_one(
            index=1,
            path=model_source_path,
            prompt=ASSET_PROMPT,
            schema_name="global_key_assets",
            response_schema=ASSET_SCHEMA,
            include_segment_metadata=False,
        )
        assets = normalize_global_assets(raw_assets)

        await _report(progress, 42, "detecting_scenes")
        scene_paths = await asyncio.to_thread(
            self.scene_detector.split,
            source_path,
            work_dir / "scenes",
        )
        if not scene_paths:
            raise RemakePipelineError("来源视频没有可分析的镜头")
        durations = await asyncio.gather(
            *(asyncio.to_thread(self.probe_duration, path) for path in scene_paths)
        )

        catalog_context = "以下是当前片段允许引用的关键资产：\n" + json.dumps(
            compact_catalog(assets),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await _report(progress, 55, "generating_storyboards")

        async def report_scene_progress(completed: int, total: int) -> None:
            progress_value = 55 + round((completed * 32) / max(1, total))
            await _report(
                progress,
                min(87, progress_value),
                "generating_storyboards",
            )

        raw_prompts = await gateway.analyze_many(
            scene_paths,
            prompt=PROMPT_TEMPLATE,
            schema_name="professional_video_prompt_material",
            response_schema=PROMPT_SCHEMA,
            context_builder=lambda _index: catalog_context,
            on_completed=report_scene_progress,
        )
        prompts = [
            render_professional_prompt(
                raw,
                assets,
                duration_seconds=durations[index],
            )
            for index, raw in enumerate(raw_prompts)
        ]

        await _report(progress, 88, "persisting")
        analysis_requests = [dict(item) for item in gateway.timings]
        metadata = {
            "pipeline": "global_assets_professional_prompts_v4",
            "segment_count": len(scene_paths),
            "asset_call_count": 1,
            "prompt_call_count": len(scene_paths),
            "asset_count": sum(
                len(assets[key]) for key in ("characters", "scenes", "objects")
            ),
            "shot_count": len(prompts),
            "model_config_id": model_config.id,
            "model_name": model_config.model,
            "analysis_requests": analysis_requests,
            "analysis_duration_ms": sum(
                int(item.get("duration_ms", 0)) for item in analysis_requests
            ),
            "decomposition_duration_ms": max(
                0,
                round((self.clock() - pipeline_started_at) * 1000),
            ),
        }
        return RemakePipelineResult(
            assets=assets,
            prompt_document={"prompts": prompts},
            metadata=metadata,
            token_usage=dict(gateway.usage),
        )


async def _report(callback: ProgressCallback | None, value: int, stage: str) -> None:
    if callback is not None:
        await callback(value, stage)


def _probe_media_duration(path: Path) -> float:
    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        duration = float(process.stdout.strip())
    except FileNotFoundError as error:
        raise RemakePipelineError("找不到 ffprobe，无法读取镜头时长") from error
    except (subprocess.CalledProcessError, ValueError) as error:
        raise RemakePipelineError(f"无法读取镜头时长: {path.name}") from error
    if duration <= 0:
        raise RemakePipelineError(f"镜头时长无效: {path.name}")
    return duration


remake_decomposition_pipeline = RemakeDecompositionPipeline()
