from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

from prompts.remake import ASSET_SCHEMA, render_remake_prompt
from schemas.agent_workflow import RemakeShot
from test.remake_fixtures import remake_shot, design_fields, synthetic_snapshot
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
            "characters": [{"name": "将军", "label": "人物", "description": "黑甲", "visual_fields": design_fields()}],
            "scenes": [],
            "objects": [],
        }

    async def analyze_many(self, paths, **kwargs):
        self.many_calls.append((paths, kwargs))
        on_completed = kwargs.get("on_completed")
        if on_completed is not None:
            for completed in range(1, len(paths) + 1):
                await on_completed(completed, len(paths))
        return [remake_shot(index, 4.2) for index, path in enumerate(paths, start=1)]


@pytest.fixture(autouse=True)
def configured_asset_contract(monkeypatch):
    snapshot = synthetic_snapshot()
    monkeypatch.setattr('services.remake.pipeline.snapshot_skills', lambda: snapshot.model_dump())



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
    assert gateway.one_calls[0]["prompt"] == render_remake_prompt("assets", "zh")
    assert gateway.one_calls[0]["response_schema"] == ASSET_SCHEMA
    assert gateway.one_calls[0]["include_segment_metadata"] is False
    assert len(gateway.many_calls) == 1
    assert gateway.many_calls[0][0] == scenes
    assert gateway.many_calls[0][1]["prompt"] == render_remake_prompt("shots", "zh")
    assert gateway.many_calls[0][1]["response_schema"] == RemakeShot.model_json_schema()
    catalog = gateway.many_calls[0][1]["context_builder"](1)
    assert catalog["assets"][0]["id"] == "character-001"
    assert catalog["duration_seconds"] == 4.2
    assert "三视图" not in str(catalog)
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


@pytest.mark.asyncio
async def test_duration_probes_do_not_fan_out_subprocesses(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    paths = [tmp_path / f"scene-{index}.mp4" for index in range(8)]
    active = maximum = 0
    lock = threading.Lock()
    probed = []

    def probe(path):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.01)
        probed.append(path)
        with lock:
            active -= 1
        return 4.2

    pipeline = RemakeDecompositionPipeline(
        scene_detector=_Detector(paths), gateway_factory=lambda _: _Gateway(),
        prepare_video=lambda path, *_args, **_kwargs: path, probe_duration=probe,
    )
    await pipeline.run(source_path=source, model_config=SimpleNamespace(id=1, model="vision"),
                       work_dir=tmp_path / "work")
    assert maximum == 1
    assert probed == paths


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_remote_mode_never_runs_media_locally(monkeypatch, tmp_path, fails):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from services.remake.remote_media import RemoteMediaError

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    gateway = _Gateway()
    remote = SimpleNamespace(prepare=AsyncMock(return_value=source),
                             split=AsyncMock(return_value=([source], [4.2])))
    if fails:
        remote.prepare.side_effect = RemoteMediaError("offline")
    closed = []

    @asynccontextmanager
    async def session():
        try:
            yield remote
        finally:
            closed.append(True)

    monkeypatch.setattr("services.remake.pipeline.media_session", session)
    def local(*_args, **_kwargs):
        pytest.fail("remote failure must not fall back onto the small server")
    pipeline = RemakeDecompositionPipeline(prepare_video=local,
        scene_detector=SimpleNamespace(split=local), probe_duration=local,
        gateway_factory=lambda _: gateway)
    arguments = dict(source_path=source, model_config=SimpleNamespace(id=1, model="test"), work_dir=tmp_path / "work")
    if fails:
        with pytest.raises(RemoteMediaError, match="offline"):
            await pipeline.run(**arguments)
        assert not gateway.one_calls
        remote.split.assert_not_called()
    else:
        result = await pipeline.run(**arguments)
        assert result.metadata["segment_count"] == 1
        remote.prepare.assert_awaited_once()
        remote.split.assert_awaited_once()
        assert len(gateway.one_calls) == 1
    assert closed == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_enabled,provider", [(False, "password"), (False, "qiling"), (True, "password"), (True, "qiling")])
async def test_unconfigured_worker_keeps_media_local(monkeypatch, tmp_path, auth_enabled, provider):
    from config import settings
    from unittest.mock import Mock

    monkeypatch.setattr(settings, "AUTH_ENABLED", auth_enabled)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", provider)
    monkeypatch.setattr(settings, "REMAKE_MEDIA_SSH_HOST", "")
    remote = Mock(side_effect=AssertionError("no worker configured"))
    monkeypatch.setattr("services.remake.remote_media.RemoteMediaSession", remote)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    prepare = Mock(return_value=source)
    probe = Mock(return_value=4.2)
    detector = _Detector([source])
    pipeline = RemakeDecompositionPipeline(prepare_video=prepare, scene_detector=detector,
        probe_duration=probe, gateway_factory=lambda _: _Gateway())
    result = await pipeline.run(source_path=source, model_config=SimpleNamespace(id=1, model="test"),
                                work_dir=tmp_path / "work")
    assert result.metadata["segment_count"] == 1
    prepare.assert_called_once()
    probe.assert_called_once_with(source)
    assert len(detector.calls) == 1
    remote.assert_not_called()


@pytest.mark.asyncio
async def test_retry_uses_saved_assets_and_scene_files_without_detecting_again(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from services.remake.checkpoints import write_scene_manifest
    from services.creation_agent.skill_execution import current_execution
    source = tmp_path/'source.mp4'
    source.write_bytes(b'source')
    cache = tmp_path/'clips'
    cache.mkdir()
    paths = [cache/'scene-001.mp4', cache/'scene-002.mp4']
    for path in paths:
        path.write_bytes(b'clip')
    write_scene_manifest(cache, paths, [4.2, 4.2])
    gateway = _Gateway()
    assets = {'characters':[{'name':'将军','description':'黑甲'}], 'scenes':[], 'objects':[]}
    monkeypatch.setattr('services.remake.pipeline.completed_outputs', AsyncMock(return_value={
        'model:remake:RemakeAssets:1':assets, 'model:remake:RemakeShot:2':remake_shot(2)}))
    monkeypatch.setattr('services.remake.pipeline.media_session', lambda: pytest.fail('unexpected media session'))
    pipeline = RemakeDecompositionPipeline(gateway_factory=lambda _:gateway,
        prepare_video=lambda *a, **kw:pytest.fail('unexpected prepare'), scene_detector=_Detector([]))
    token = current_execution.set(SimpleNamespace(params={},snapshot=synthetic_snapshot(),language='zh'))
    try:
        result = await pipeline.run(source_path=source, model_config=SimpleNamespace(id=9,model='test',name='test'),
                                    work_dir=tmp_path/'retry',scene_cache=cache)
    finally:
        current_execution.reset(token)
    assert gateway.one_calls == [] and pipeline.scene_detector.calls == []
    assert gateway.many_calls[0][1]['completed_results'] == {2:remake_shot(2)}
    assert result.metadata['asset_call_count'] == 0 and result.metadata['prompt_call_count'] == 1


@pytest.mark.asyncio
async def test_continuous_pipeline_overlaps_media_and_model_and_routes_previous_shot_evidence(tmp_path, monkeypatch):
    import asyncio
    import json
    from services.remake.gateway import RemakeVideoAnalysisGateway
    from test.test_services.test_remake_persistence import _source
    from models.asset import Asset

    source = await _source()
    hero = await Asset.create(novel_id=source.novel_id, asset_type=1, canonical_name='将军', aliases=['统领'],
                              description='人工描述', base_traits='用户设定')
    entered, extracted = threading.Event(), threading.Event()
    class Detector:
        def split_timeline(self, path, out):
            entered.set()
            assert extracted.wait(timeout=5)
            out.mkdir(parents=True)
            for i in range(1, 4):
                (out / f'{i}.mp4').write_bytes(bytes([i]))
            (out / 'boundaries.json').write_text(json.dumps({f'{i}.mp4':{'start_seconds':(i-1)*4.2,
                'end_seconds':i*4.2} for i in range(1,4)}))
            return sorted(out.glob('*.mp4'))

    calls = []
    class Gateway(RemakeVideoAnalysisGateway):
        async def analyze_one(self, **kw):
            calls.append(kw)
            if kw['schema_name'] == 'global_key_assets':
                assert await asyncio.to_thread(entered.wait, 5)
                extracted.set()
                assert kw['context']['project_assets'][0]['project_asset_id'] == hero.id
                return {'characters':[{'name':'统领','label':'人物','description':'外貌','visual_fields':design_fields()}],
                        'scenes':[], 'objects':[]}
            i = kw['index']
            assert kw['context']['assets'][0]['name'] == '将军'
            assert kw['context']['source_interval']['start_seconds'] == (i-1)*4.2
            if i > 1:
                assert kw['context']['previous_shot']['dialogue'] == [f'0s-1s: 将军（平静）：第{i-1}句']
            else:
                assert 'previous_shot' not in kw['context']
            return {**remake_shot(i), 'dialogue':[f'0s-1s: 将军（平静）：第{i}句']}
    config = SimpleNamespace(id=9, model='test', concurrency=3)
    gateway = Gateway(config, client=object())
    video = tmp_path / 'sample.mp4'
    video.write_bytes(b'video')
    monkeypatch.setattr('services.remake.pipeline.media_session', lambda: __import__('contextlib').nullcontext(None))
    result = await RemakeDecompositionPipeline(scene_detector=Detector(), gateway_factory=lambda _:gateway,
        prepare_video=lambda path, *a, **kw:path).run(source=source, source_path=video, work_dir=tmp_path/'work', model_config=config)
    assert [s['sequence'] for s in result.prompt_document['prompts']] == [1,2,3]
    assert result.assets['characters'][0]['project_asset_id'] == hero.id
    assert len(calls) == 4
    await hero.refresh_from_db()
    assert hero.base_traits == '用户设定'


@pytest.mark.parametrize("entries", [{"file":"a"}, [None], [{"file":"bad.mp4","size":1,"duration":0}], [{"file":"../outside","size":1,"duration":1}]])
def test_damaged_or_invalid_clip_manifest_is_not_used(tmp_path, entries):
    import json
    from services.remake.checkpoints import read_scene_manifest
    (tmp_path/'bad.mp4').write_bytes(b'x')
    (tmp_path/'manifest.json').write_text(json.dumps(entries))
    assert read_scene_manifest(tmp_path) is None


@pytest.mark.asyncio
async def test_new_batch_dispatches_every_shot_before_assets_or_previous_shots_finish(tmp_path,monkeypatch):
    import asyncio
    import json
    from unittest.mock import AsyncMock
    from models.ai_task import AiTask
    from services.creation_agent.skill_execution import current_execution
    from services.remake.persistence import remake_result_persistence

    counts = (35, 35, 33)
    all_started = asyncio.Event()
    calls = []
    sources = [SimpleNamespace(episode_number=i+1) for i in range(len(counts))]
    monkeypatch.setattr(remake_result_persistence, "project_catalog", AsyncMock(return_value=[]))
    tasks = [await AiTask.create(task_type=6, status=2) for _ in counts]
    class Detector:
        def split_timeline(self, path, out):
            out.mkdir(parents=True)
            paths = [out/f'scene-{i:03d}.mp4' for i in range(1, counts[int(path.stem)]+1)]
            for clip in paths:
                clip.write_bytes(b'clip')
            (out/'boundaries.json').write_text(json.dumps({p.name:{'start_seconds':i*4, 'end_seconds':(i+1)*4}
                                                           for i,p in enumerate(paths)}))
            return paths
    bind = AsyncMock(side_effect=lambda source, assets, catalog: assets)
    monkeypatch.setattr(remake_result_persistence,'bind_assets',bind)
    monkeypatch.setattr('services.remake.pipeline.media_session', lambda: __import__('contextlib').nullcontext(None))

    class Gateway(_Gateway):
        async def analyze_one(self, **kw):
            calls.append(kw)
            if len(calls)==sum(counts)+len(counts):
                all_started.set()
            await asyncio.wait_for(all_started.wait(),5)
            if kw['schema_name']=='global_key_assets':
                return {'characters':[{'name':'将军','description':'已登记'}],'scenes':[],'objects':[]}
            i=kw['index']
            assert (kw['previous_path'].name if kw['previous_path'] else None)==(f'scene-{i-1:03d}.mp4' if i>1 else None)
            assert 'previous_shot' not in kw['context']
            return remake_shot(i,4,[{'asset_id':f'local-{i}','asset_name':'将军','asset_type':'character'}])
        async def analyze_many(self, paths, **kwargs):
            pytest.fail('No draft, audit, or serial repair loop may run')

    async def episode(e):
        video=tmp_path/f'{e}.mp4'
        video.write_bytes(b'video')
        execution=SimpleNamespace(params={'task_id':str(tasks[e].id),'remake_context_version':5},
                                  snapshot=synthetic_snapshot(), language='zh')
        token=current_execution.set(execution)
        try:
            pipeline=RemakeDecompositionPipeline(scene_detector=Detector(),gateway_factory=lambda _:Gateway(),
                                                 prepare_video=lambda p,*a,**kw:p)
            return await pipeline.run(source=sources[e],source_path=video,work_dir=tmp_path/f'work-{e}',
                                      model_config=SimpleNamespace(id=1,model='mock',concurrency=100))
        finally:
            current_execution.reset(token)
    results=await asyncio.gather(*(episode(e) for e in range(len(counts))))
    assert len(calls)==106
    for count,result in zip(counts,results,strict=True):
        assert [r['shot_index'] for r in result.prompt_document['prompts']]==list(range(1,count+1))
        assert all(r['asset_refs'][0]['asset_id']=='character-001' for r in result.prompt_document['prompts'])
        assert result.metadata['pipeline']=='parallel_source_shots'
