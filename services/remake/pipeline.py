"""重制视频全局资产与逐镜头专业 Prompt 拆解流水线。"""

from __future__ import annotations

from utils.messages import localized_message

from contextlib import nullcontext
import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompts.remake import ASSET_SCHEMA, render_remake_prompt
from prompts.skill_pack import SkillSnapshot, snapshot_skills
from schemas.agent_workflow import RemakeShot
from services.language import task_language
from services.remake.checkpoints import completed_outputs, read_scene_manifest, write_scene_manifest
from services.remake.gateway import MAX_MODEL_VIDEO_BYTES, RemakeVideoAnalysisGateway
from services.remake.media_prepare import prepare_video_for_model_input, probe_media_duration
from services.remake.remote_media import RemoteMediaSession, media_session
from services.remake.prompt_render import (
    compact_catalog,
    normalize_global_assets,
)
from services.remake.scene_detection import SceneDetector, scene_detector
from services.remake.storyboards import prepare_remake_prompt
from services.remake.asset_validation import render_remake_assets
from services.storyboard.strategies import storyboard_strategy_factory


class RemakePipelineError(RuntimeError):
    pass


class RemakeAwaitingResults(RemakePipelineError):
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
        storyboard_strategy: str | None = None,
        aspect_ratio: str = '16:9',
        scene_cache: Path | None = None,
    ) -> RemakePipelineResult:
        cached = read_scene_manifest(scene_cache) if scene_cache else None
        async with (nullcontext(None) if cached else media_session()) as remote:
            return await self._run(source_path=source_path, model_config=model_config, work_dir=work_dir,
                                   progress=progress, storyboard_strategy=storyboard_strategy,
                                   aspect_ratio=aspect_ratio, remote=remote, scene_cache=scene_cache, cached=cached)

    async def _run(
        self, *, source_path: Path, model_config: Any, work_dir: Path,
        progress: ProgressCallback | None, storyboard_strategy: str | None,
        aspect_ratio: str, remote: RemoteMediaSession | None, scene_cache: Path | None, cached,
    ) -> RemakePipelineResult:
        pipeline_started_at = self.clock()
        if not source_path.is_file():
            raise RemakePipelineError(localized_message('来源视频不存在'))
        work_dir.mkdir(parents=True, exist_ok=True)
        await _report(progress, 10, "preparing")
        gateway = self.gateway_factory(model_config)
        from services.creation_agent.skill_execution import current_execution
        execution = current_execution.get()
        snapshot = execution.snapshot if execution else SkillSnapshot.model_validate(snapshot_skills())
        language = execution.language if execution else task_language.get() or 'zh'
        strategy = storyboard_strategy_factory.resolve(storyboard_strategy).key
        saved = await completed_outputs({**execution.params, 'retry_of_task_id': execution.params.get('task_id') or execution.params.get('retry_of_task_id'), 'model_config_id':model_config.id}) if execution else {}
        raw_assets = saved.get('model:remake:RemakeAssets:1')
        if cached is None or raw_assets is None:
            if remote:
                model_source_path = await remote.prepare(source_path, work_dir / "model-input", max_bytes=MAX_MODEL_VIDEO_BYTES)
            else:
                model_source_path = await asyncio.to_thread(
                    self.prepare_video, source_path, work_dir / "model-input", max_bytes=MAX_MODEL_VIDEO_BYTES,
                )

        await _report(progress, 20, "extracting_assets")
        if raw_assets is None:
            raw_assets = await gateway.analyze_one(
                index=1,
                path=model_source_path,
                prompt="" if execution else render_remake_prompt("assets", task_language.get() or "zh"),
                schema_name="global_key_assets",
                response_schema=ASSET_SCHEMA,
                include_segment_metadata=False,
            )
        if not execution:
            raw_assets = render_remake_assets(raw_assets, snapshot, language, aspect_ratio)
        assets = normalize_global_assets(raw_assets, language)

        await _report(progress, 42, "detecting_scenes")
        directory = scene_cache or work_dir / "scenes"
        if cached:
            scene_paths, durations = cached
        elif remote:
            scene_paths, durations = await remote.split(directory)
        else:
            scene_paths = await asyncio.to_thread(self.scene_detector.split, model_source_path, directory)
            if not scene_paths:
                raise RemakePipelineError(localized_message('来源视频没有可分析的镜头'))
            # Each probe starts a process; do not multiply native buffers by shot count.
            durations = [await asyncio.to_thread(self.probe_duration, path) for path in scene_paths]

        if scene_cache and not cached:
            write_scene_manifest(scene_cache, scene_paths, durations)

        catalog = compact_catalog(assets, snapshot=snapshot, language=language)
        await _report(progress, 55, "generating_storyboards")

        async def report_scene_progress(completed: int, total: int) -> None:
            progress_value = 55 + round((completed * 32) / max(1, total))
            await _report(
                progress,
                min(87, progress_value),
                "generating_storyboards",
            )

        completed = {i: saved[f'model:remake:RemakeShot:{i}'] for i in range(1, len(scene_paths) + 1)
                     if f'model:remake:RemakeShot:{i}' in saved}
        held = frozenset(execution.params.get("held_shots", [])) - completed.keys() if execution else set()
        raw_prompts = await gateway.analyze_many(
            scene_paths,
            prompt="" if execution else render_remake_prompt("shots", task_language.get() or "zh"),
            schema_name="professional_video_prompt_material",
            response_schema=RemakeShot.model_json_schema(),
            context_builder=lambda index: {'assets': catalog, 'duration_seconds': durations[index - 1],
                                          'storyboard_strategy': strategy},
            on_completed=report_scene_progress,
            **({"held_shots": held} if held else {}),
            **({"completed_results": completed} if completed else {}),
        )
        if held:
            await _report(progress, 55 + round(32 * len(raw_prompts) / len(scene_paths)), "needs_review")
            raise RemakeAwaitingResults("剩余片段未完成，可以重试")
        prompts = [prepare_remake_prompt(raw, catalog, snapshot, language,
            strategy_key=strategy, duration_seconds=durations[index]) for index, raw in enumerate(raw_prompts)]

        await _report(progress, 88, "persisting")
        analysis_requests = [dict(item) for item in gateway.timings]
        metadata = {
            "pipeline": "global_assets_professional_prompts_v4",
            "segment_count": len(scene_paths),
            "asset_call_count": int("model:remake:RemakeAssets:1" not in saved),
            "prompt_call_count": len(scene_paths) - len(completed),
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
        return probe_media_duration(path)
    except RuntimeError as error:
        raise RemakePipelineError(str(error)) from error


remake_decomposition_pipeline = RemakeDecompositionPipeline()
