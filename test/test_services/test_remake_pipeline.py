from pathlib import Path
from types import SimpleNamespace

import pytest

from prompts.remake import ASSET_PROMPT, ASSET_SCHEMA, PROMPT_SCHEMA, PROMPT_TEMPLATE
from services.remake.pipeline import RemakeDecompositionPipeline, RemakePipelineError


class _Detector:
    def __init__(self, scenes: list[Path]):
        self.scenes = scenes
        self.calls = []

    def split(self, source: Path, output: Path) -> list[Path]:
        self.calls.append((source, output))
        return self.scenes


class _Gateway:
    def __init__(self):
        self.one_calls = []
        self.many_calls = []
        self.usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        self.timings = [
            {"index": 1, "schema_name": "global_key_assets", "duration_ms": 1200, "attempts": 1, "status": "completed"},
            {"index": 1, "schema_name": "professional_video_prompt_material", "duration_ms": 800, "attempts": 1, "status": "completed"},
        ]

    async def analyze_one(self, **kwargs):
        self.one_calls.append(kwargs)
        return {
            "characters": [{"name": "将军", "label": "人物", "description": "黑甲"}],
            "scenes": [],
            "objects": [],
        }

    async def analyze_many(self, paths, **kwargs):
        self.many_calls.append((paths, kwargs))
        on_completed = kwargs.get("on_completed")
        if on_completed is not None:
            for completed in range(1, len(paths) + 1):
                await on_completed(completed, len(paths))
        return [
            {
                "shot_index": index,
                "file": path.name,
                "asset_refs": [
                    {"asset_id": "character-001", "asset_name": "将军", "asset_type": "character"}
                ],
                "style": {"visual_style": "写实", "cinematography": "24fps", "color_tone": "暖色"},
                "global_conditions": {"time_weather": "夜", "environment_light": "烛光", "spatial_relationships": "将军居中"},
                "audio": {"has_bgm": False, "bgm_description": ""},
                "shots": [
                    {"order": 1, "start_seconds": 0, "end_seconds": 4.2, "title": "近景", "camera": "固定", "description": "将军抬眼", "environment_sound": "风声", "dialogues": []}
                ],
                "transition": "硬切",
                "effects": {"forbidden": "禁止变形", "allowed": "自然景深"},
                "confidence": 0.9,
            }
            for index, path in enumerate(paths, start=1)
        ]


@pytest.mark.asyncio
async def test_pipeline_calls_global_assets_once_then_one_prompt_per_scene_in_order(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    scenes = [tmp_path / "scene-001.mp4", tmp_path / "scene-002.mp4"]
    for scene in scenes:
        scene.write_bytes(b"scene")
    detector = _Detector(scenes)
    gateway = _Gateway()
    prepare_calls = []
    progress = []

    def prepare(path, cache_dir, *, max_bytes):
        prepare_calls.append((path, cache_dir, max_bytes))
        return path

    async def report(value, stage):
        progress.append((value, stage))

    pipeline = RemakeDecompositionPipeline(
        scene_detector=detector,
        gateway_factory=lambda _config: gateway,
        prepare_video=prepare,
        probe_duration=lambda _path: 4.2,
        clock=iter([20.0, 22.5]).__next__,
    )
    result = await pipeline.run(
        source_path=source,
        model_config=SimpleNamespace(id=9, name="视觉模型", model="vision", concurrency=2),
        work_dir=tmp_path / "work",
        progress=report,
    )

    assert len(gateway.one_calls) == 1
    assert gateway.one_calls[0]["prompt"] == ASSET_PROMPT
    assert gateway.one_calls[0]["response_schema"] == ASSET_SCHEMA
    assert gateway.one_calls[0]["include_segment_metadata"] is False
    assert len(gateway.many_calls) == 1
    assert gateway.many_calls[0][0] == scenes
    assert gateway.many_calls[0][1]["prompt"] == PROMPT_TEMPLATE
    assert gateway.many_calls[0][1]["response_schema"] == PROMPT_SCHEMA
    catalog = gateway.many_calls[0][1]["context_builder"](1)
    assert "character-001" in catalog
    assert "三视图" not in catalog
    assert [item["file"] for item in result.prompt_document["prompts"]] == [
        "scene-001.mp4",
        "scene-002.mp4",
    ]
    assert result.metadata == {
        "pipeline": "global_assets_professional_prompts_v4",
        "segment_count": 2,
        "asset_call_count": 1,
        "prompt_call_count": 2,
        "asset_count": 1,
        "shot_count": 2,
        "model_config_id": 9,
        "model_name": "vision",
        "analysis_duration_ms": 2000,
        "decomposition_duration_ms": 2500,
        "analysis_requests": gateway.timings,
    }
    assert result.token_usage == gateway.usage
    assert progress == [
        (10, "preparing"),
        (20, "extracting_assets"),
        (42, "detecting_scenes"),
        (55, "generating_storyboards"),
        (71, "generating_storyboards"),
        (87, "generating_storyboards"),
        (88, "persisting"),
    ]


@pytest.mark.asyncio
async def test_pipeline_rejects_empty_scene_split(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    pipeline = RemakeDecompositionPipeline(
        scene_detector=_Detector([]),
        gateway_factory=lambda _config: _Gateway(),
        prepare_video=lambda path, _cache, *, max_bytes: path,
        probe_duration=lambda _path: 4.0,
    )

    with pytest.raises(RemakePipelineError, match="没有可分析的镜头"):
        await pipeline.run(
            source_path=source,
            model_config=SimpleNamespace(id=1, name="模型", model="vision", concurrency=1),
            work_dir=tmp_path / "work",
        )
