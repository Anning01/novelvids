import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.remake.gateway import (
    ANALYSIS_TIMEOUT_SECONDS,
    RemakeVideoAnalysisError,
    RemakeVideoAnalysisGateway,
)


class _CompletionEndpoint:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    async def create(self, **request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _Client:
    def __init__(self, responses):
        self.endpoint = _CompletionEndpoint(responses)
        self.chat = SimpleNamespace(completions=self.endpoint)


def _completion(payload: dict, *, prompt_tokens: int = 3, completion_tokens: int = 5):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(payload), refusal=None),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _config(**overrides):
    values = {
        "base_url": "https://example.test/v1",
        "api_key": "secret-key-that-must-not-leak",
        "model": "video-understanding-model",
        "concurrency": 2,
        "max_tokens": 4096,
        "supports_json_output": True,
        "thinking": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_multiple_analysis_calls_accumulate_cached_input():
    gateway = RemakeVideoAnalysisGateway(_config(), client=_Client([]))
    gateway._add_usage({'prompt_tokens': 1000, 'completion_tokens': 20, 'total_tokens': 1020, 'cache_read_tokens': 800})
    gateway._add_usage({'prompt_tokens': 500, 'completion_tokens': 10, 'total_tokens': 510, 'cache_read_tokens': 300})
    assert gateway.usage == {'prompt_tokens': 1500, 'completion_tokens': 30, 'total_tokens': 1530, 'cache_read_tokens': 1100}


@pytest.mark.asyncio
async def test_gateway_sends_compatible_json_mode_schema_instruction_and_video_data_url(tmp_path: Path):
    video = tmp_path / "scene.mov"
    video.write_bytes(b"video-bytes")
    client = _Client([_completion({"ok": True})])
    gateway = RemakeVideoAnalysisGateway(_config(), client=client)

    result = await gateway.analyze_one(
        index=2,
        path=video,
        prompt="分析片段",
        context="只允许引用资产",
        schema_name="scene_material",
        response_schema={"type": "object"},
    )

    assert result == {"ok": True, "shot_index": 2, "file": "scene.mov"}
    request = client.endpoint.requests[0]
    assert request["model"] == "video-understanding-model"
    assert "reasoning_effort" not in request
    assert request["max_tokens"] == 4096
    assert request["response_format"] == {"type": "json_object"}
    content = request["messages"][0]["content"]
    import json
    assert content[0]["text"].startswith("分析片段\n")
    facts = json.loads(content[0]["text"].split("\n", 1)[1])["untrusted_task_facts"]
    assert facts == {"assets": "只允许引用资产", "segment": 2, "schema": {"type": "object"}}
    assert content[1]["type"] == "video_url"
    assert content[1]["video_url"]["url"].startswith("data:video/quicktime;base64,")
    assert content[1]["video_url"]["fps"] == 1.0
    assert gateway.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 5,
        "total_tokens": 8,
    }


@pytest.mark.asyncio
async def test_gateway_omits_optional_provider_parameters_when_capabilities_are_disabled(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    client = _Client([_completion({"ok": True})])
    gateway = RemakeVideoAnalysisGateway(
        _config(supports_json_output=False, thinking=None, max_tokens=None),
        client=client,
    )

    await gateway.analyze_one(
        index=1,
        path=video,
        prompt="prompt",
        schema_name="schema",
        response_schema={"type": "object"},
    )

    request = client.endpoint.requests[0]
    assert "response_format" not in request
    assert "reasoning_effort" not in request
    assert "extra_body" not in request
    assert "max_tokens" not in request


@pytest.mark.asyncio
async def test_gateway_sends_reasoning_only_when_thinking_is_enabled(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    client = _Client([_completion({"ok": True})])
    gateway = RemakeVideoAnalysisGateway(
        _config(thinking="enabled"),
        client=client,
    )

    await gateway.analyze_one(
        index=1,
        path=video,
        prompt="prompt",
        schema_name="schema",
        response_schema={"type": "object"},
    )

    request = client.endpoint.requests[0]
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request["reasoning_effort"] == "minimal"


@pytest.mark.asyncio
async def test_gateway_sends_doubao_compatible_disabled_thinking_without_reasoning(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    client = _Client([_completion({"ok": True})])
    gateway = RemakeVideoAnalysisGateway(_config(thinking="disabled"), client=client)

    await gateway.analyze_one(
        index=1,
        path=video,
        prompt="prompt",
        schema_name="schema",
        response_schema={"type": "object"},
    )

    request = client.endpoint.requests[0]
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in request


def test_gateway_configures_single_ten_minute_timeout_without_sdk_retries():
    captured = {}

    def client_factory(**kwargs):
        captured.update(kwargs)
        return _Client([])

    RemakeVideoAnalysisGateway(_config(), client_factory=client_factory)

    assert captured["timeout"] == ANALYSIS_TIMEOUT_SECONDS == 600.0
    assert captured["max_retries"] == 0


@pytest.mark.asyncio
async def test_gateway_retries_invalid_json_and_aggregates_all_consumed_usage(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    invalid = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="bad", refusal=None))],
        usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
    )
    client = _Client([invalid, _completion({"value": 1}, prompt_tokens=4, completion_tokens=6)])
    gateway = RemakeVideoAnalysisGateway(_config(), client=client, retry_delays=(0, 0))

    result = await gateway.analyze_one(
        index=1,
        path=video,
        prompt="prompt",
        schema_name="schema",
        response_schema={"type": "object"},
    )

    assert result["value"] == 1
    assert len(client.endpoint.requests) == 2
    assert gateway.usage == {
        "prompt_tokens": 6,
        "completion_tokens": 7,
        "total_tokens": 13,
    }


@pytest.mark.asyncio
async def test_gateway_failure_is_stable_and_does_not_leak_provider_or_secret(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    provider_error = RuntimeError("secret-key-that-must-not-leak provider payload")
    client = _Client([provider_error, provider_error, provider_error])
    gateway = RemakeVideoAnalysisGateway(_config(), client=client, retry_delays=(0, 0))

    with pytest.raises(RemakeVideoAnalysisError) as raised:
        await gateway.analyze_one(
            index=7,
            path=video,
            prompt="prompt",
            schema_name="schema",
            response_schema={"type": "object"},
        )

    assert "第 7 个视频片段分析失败" in str(raised.value)
    assert "provider payload" in str(raised.value)
    assert "secret-key" not in str(raised.value)
    assert "REMAKE_VIDEO_ANALYSIS_FAILED" not in str(raised.value)
    assert len(client.endpoint.requests) == 3


@pytest.mark.asyncio
async def test_gateway_forwards_actual_provider_error_message(tmp_path: Path):
    class _ProviderError(RuntimeError):
        status_code = None
        body = {
            "error": {
                "message": "视频分辨率过高，不支持 4K 视频",
                "code": "InvalidVideoFormat",
            }
        }

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    client = _Client([_ProviderError()])
    gateway = RemakeVideoAnalysisGateway(_config(), client=client, retry_delays=())

    with pytest.raises(RemakeVideoAnalysisError) as raised:
        await gateway.analyze_one(
            index=1,
            path=video,
            prompt="prompt",
            schema_name="schema",
            response_schema={"type": "object"},
        )

    assert "第 1 个视频片段分析失败：视频分辨率过高，不支持 4K 视频" in str(raised.value)
    assert "REMAKE_VIDEO_ANALYSIS_FAILED" not in str(raised.value)


@pytest.mark.asyncio
async def test_gateway_does_not_retry_provider_4xx_and_logs_only_safe_metadata(
    tmp_path: Path,
    caplog,
):
    class _BadRequest(RuntimeError):
        status_code = 400
        request_id = "request-safe-id"
        body = {
            "error": {
                "code": "InvalidParameter",
                "message": "secret-key-that-must-not-leak provider payload",
            }
        }

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    client = _Client([_BadRequest("secret-key-that-must-not-leak")])
    gateway = RemakeVideoAnalysisGateway(_config(), client=client, retry_delays=(0, 0))

    with caplog.at_level("WARNING"), pytest.raises(RemakeVideoAnalysisError) as raised:
        await gateway.analyze_one(
            index=1,
            path=video,
            prompt="prompt",
            schema_name="schema",
            response_schema={"type": "object"},
        )

    assert len(client.endpoint.requests) == 1
    assert raised.value.error_code == "REMAKE_ANALYSIS_REQUEST_INVALID"
    assert "当前模型能力不兼容" in str(raised.value)
    assert "status=400" in caplog.text
    assert "code=InvalidParameter" in caplog.text
    assert "request_id=request-safe-id" in caplog.text
    assert "secret-key-that-must-not-leak" not in caplog.text


@pytest.mark.asyncio
async def test_gateway_analyze_many_limits_concurrency_and_preserves_input_order(tmp_path: Path):
    paths = []
    for index in range(4):
        path = tmp_path / f"scene-{index}.mp4"
        path.write_bytes(b"video")
        paths.append(path)
    gateway = RemakeVideoAnalysisGateway(_config(concurrency=2), client=_Client([]))
    current = 0
    maximum = 0

    async def analyze_one(**kwargs):
        nonlocal current, maximum
        current += 1
        maximum = max(maximum, current)
        await asyncio.sleep((5 - kwargs["index"]) * 0.001)
        current -= 1
        return {"shot_index": kwargs["index"]}

    gateway.analyze_one = analyze_one
    completed = []

    async def on_completed(done: int, total: int):
        completed.append((done, total))

    results = await gateway.analyze_many(
        paths,
        prompt="prompt",
        schema_name="schema",
        response_schema={"type": "object"},
        on_completed=on_completed,
    )

    assert maximum == 2
    assert [item["shot_index"] for item in results] == [1, 2, 3, 4]
    assert completed == [(1, 4), (2, 4), (3, 4), (4, 4)]


@pytest.mark.asyncio
async def test_gateway_records_safe_request_duration(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    clock = iter([10.0, 10.25]).__next__
    gateway = RemakeVideoAnalysisGateway(
        _config(),
        client=_Client([_completion({"ok": True})]),
        clock=clock,
    )

    await gateway.analyze_one(
        index=3,
        path=video,
        prompt="prompt",
        schema_name="professional_video_prompt_material",
        response_schema={"type": "object"},
    )

    assert gateway.timings == [{
        "index": 3,
        "schema_name": "professional_video_prompt_material",
        "duration_ms": 250,
        "attempts": 1,
        "status": "completed",
    }]


@pytest.mark.asyncio
async def test_gateway_rejects_video_larger_than_model_limit_before_call(tmp_path: Path, monkeypatch):
    video = tmp_path / "too-large.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr("services.remake.gateway.MAX_MODEL_VIDEO_BYTES", 0)
    client = _Client([])
    gateway = RemakeVideoAnalysisGateway(_config(), client=client)

    with pytest.raises(RemakeVideoAnalysisError, match="模型输入视频超过"):
        await gateway.analyze_one(
            index=1,
            path=video,
            prompt="prompt",
            schema_name="schema",
            response_schema={"type": "object"},
        )

    assert client.endpoint.requests == []


@pytest.mark.asyncio
async def test_skill_video_uses_binary_directly_without_base64_round_trip(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from services.creation_agent.skill_execution import current_execution
    from schemas.agent_workflow import RemakeAssets

    video = tmp_path / "source.mov"
    video.write_bytes(b"original-video-bytes")
    gateway = RemakeVideoAnalysisGateway(_config(), client=_Client([]))
    execution = SimpleNamespace(generate=AsyncMock(return_value=RemakeAssets(characters=[], scenes=[], objects=[])))
    monkeypatch.setattr("services.remake.gateway.base64.b64encode", lambda _: pytest.fail("video was base64 copied"))
    token = current_execution.set(execution)
    try:
        await gateway.analyze_one(index=1, path=video, prompt="", schema_name="global_key_assets",
                                  response_schema={}, include_segment_metadata=False)
    finally:
        current_execution.reset(token)
    content = execution.generate.call_args.kwargs["media"][0]
    assert content.data == b"original-video-bytes"
    assert content.media_type == "video/quicktime"
    assert content.vendor_metadata == {"fps": 1.0}


@pytest.mark.asyncio
async def test_skill_video_still_checks_size_before_model_call(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from services.creation_agent.skill_execution import current_execution

    video = tmp_path / "source.mp4"
    video.write_bytes(b"oversize")
    execution = SimpleNamespace(generate=AsyncMock())
    monkeypatch.setattr("services.remake.gateway.MAX_MODEL_VIDEO_BYTES", 1)
    gateway = RemakeVideoAnalysisGateway(_config(), client=_Client([]))
    token = current_execution.set(execution)
    try:
        with pytest.raises(RemakeVideoAnalysisError, match="模型输入视频超过"):
            await gateway.analyze_one(index=1, path=video, prompt="", schema_name="global_key_assets", response_schema={})
    finally:
        current_execution.reset(token)
    execution.generate.assert_not_called()


@pytest.mark.asyncio
async def test_studio_remake_sends_media_link_with_sampling_rate(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from services.creation_agent.skill_execution import current_execution, _audit_messages
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from services.creation_agent.model_usage import UsagePreservingChatModel
    from schemas.agent_workflow import RemakeAssets

    video = tmp_path / "source.mp4"
    video.write_bytes(b"test video")
    url = "https://bucket.oss-cn-beijing.aliyuncs.com/studio-temporary/v1/test.mp4?signature=test"
    upload = AsyncMock(return_value=url)
    monkeypatch.setattr("services.oss.studio_client.studio_client", lambda *args, **kwargs: SimpleNamespace(resolve=upload))
    config = _config(api_protocol="novelvids", model="nv-9", api_key="nv_test")
    client = _Client([_completion({'characters': [], 'scenes': [], 'objects': []})])
    gateway = RemakeVideoAnalysisGateway(config, client=client)
    execution = SimpleNamespace(params={'team_id': 1}, generate=AsyncMock(return_value=RemakeAssets(characters=[], scenes=[], objects=[])))
    args = dict(index=1, path=video, prompt='', schema_name='global_key_assets', response_schema={})
    token = current_execution.set(execution)
    try:
        await gateway.analyze_one(**args)
    finally:
        current_execution.reset(token)
    item = execution.generate.call_args.kwargs['media'][0]
    expected = {'type':'video_url', 'video_url':{'url':url,'fps':1.0}}
    assert await UsagePreservingChatModel._map_video_url_item(None, item) == expected
    assert 'signature=test' not in str(_audit_messages([ModelRequest(parts=[UserPromptPart([item])])]))
    await gateway.analyze_one(**args)
    assert client.endpoint.requests[0]['messages'][0]['content'][1] == expected


@pytest.mark.asyncio
async def test_retry_charges_only_missing_indices_and_preserves_sequence(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    gateway = RemakeVideoAnalysisGateway(_config(), client=_Client([]))
    paths = [tmp_path / f'scene-{i:03}.mp4' for i in range(1, 6)]
    async def analyze(**kwargs):
        return {'shot_index':kwargs['index'], 'value':'new'}
    call = AsyncMock(side_effect=analyze)
    monkeypatch.setattr(gateway, 'analyze_one', call)
    progress = AsyncMock()
    result = await gateway.analyze_many(paths, prompt='', schema_name='shots', response_schema={},
        completed_results={1:{'value':'saved'},3:{'value':'saved'},5:{'value':'saved'}}, on_completed=progress)
    assert sorted(args.kwargs['index'] for args in call.await_args_list) == [2, 4]
    assert [s['shot_index'] for s in result] == [1, 2, 3, 4, 5]
    assert [s['value'] for s in result] == ['saved','new','saved','new','saved']
    assert progress.await_args_list[0].args == (3,5)


@pytest.mark.asyncio
async def test_partial_retry_skips_saved_and_uncertain_without_renumbering(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    gateway = RemakeVideoAnalysisGateway(_config(), client=_Client([]))
    analyze = AsyncMock(return_value={'shot_index': 3})
    monkeypatch.setattr(gateway, 'analyze_one', analyze)
    results = await gateway.analyze_many([tmp_path / f'{i}.mp4' for i in (1, 2, 3)],
        prompt='', schema_name='shots', response_schema={}, completed_results={1:{}}, held_shots=frozenset({2}))
    assert [item['shot_index'] for item in results] == [1, 3]
    assert analyze.await_count == 1 and analyze.await_args.kwargs['index'] == 3
