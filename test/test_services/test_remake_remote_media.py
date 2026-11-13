import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas.remake_media import MediaWorkerRequest, MediaScenes, PreparedMedia
from services.remake.media_worker import execute
from services.remake.remote_media import MediaWorkerConnection, RemoteMediaError, RemoteMediaSession, media_session


@pytest.mark.parametrize("model,values", [
    (MediaWorkerConnection, {"host": "-oProxyCommand=bad"}),
    (MediaWorkerConnection, {"host": "root@worker;sh"}),
    (MediaWorkerConnection, {"host": "worker", "root": "/opt/../etc"}),
    (MediaWorkerRequest, {"action": "create", "job_id": "../../etc"}),
    (PreparedMedia, {"filename": "../../key", "size_bytes": 1}),
    (MediaScenes, {"scenes": [{"filename": "../scene-001.mp4", "duration_seconds": 4}]}),
    (MediaScenes, {"scenes": [{"filename": "scene-001.mp4", "duration_seconds": float('inf')}]}),
])
def test_remote_protocol_rejects_commands_paths_and_invalid_results(model, values):
    with pytest.raises(ValidationError):
        model.model_validate(values)


def test_worker_reuses_media_algorithms_and_cleans_only_its_job(monkeypatch, tmp_path):
    job_id = uuid4()
    sibling = tmp_path / "jobs" / uuid4().hex
    sibling.mkdir(parents=True)
    work = tmp_path / "jobs" / job_id.hex
    assert execute(MediaWorkerRequest(action="create", job_id=job_id), tmp_path) == {"ok": True}
    (work / "source.mov").write_bytes(b"original video")
    preparation = []

    def prepare(source, cache, **options):
        preparation.append((source, cache, options))
        return source

    monkeypatch.setattr("services.remake.media_prepare.prepare_video_for_model_input", prepare)
    prepared = execute(MediaWorkerRequest(action="prepare", job_id=job_id, extension=".mov"), tmp_path)
    assert prepared == {"filename": "model.mov", "size_bytes": 14}
    assert (work / "model.mov").read_bytes() == b"original video"
    assert preparation[0][2] == {"max_bytes": 35_000_000}

    def split(source, destination):
        assert source == work / "model.mov"
        destination.mkdir()
        paths = [destination / f"scene-{n:03d}.mp4" for n in (1, 2)]
        for path in paths:
            path.write_bytes(b"clip")
        return paths

    monkeypatch.setattr("services.remake.scene_detection.scene_detector.split", split)
    monkeypatch.setattr("services.remake.media_prepare.probe_media_duration", lambda _: 4.0)
    result = execute(MediaWorkerRequest(action="split", job_id=job_id), tmp_path)
    assert [s["filename"] for s in result["scenes"]] == ["scene-001.mp4", "scene-002.mp4"]
    stopped = []
    monkeypatch.setattr("services.remake.media_worker.subprocess.run", lambda cmd, **_: stopped.append(cmd))
    execute(MediaWorkerRequest(action="cleanup", job_id=job_id), tmp_path)
    assert not work.exists() and sibling.is_dir()
    assert [cmd[-1] for cmd in stopped] == [f"novelvids-remake-{job_id.hex}-{phase}.service" for phase in ("prepare", "split", "process")]


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['split', 'process'])
async def test_ssh_commands_bound_resources_and_require_known_host(monkeypatch, action):
    worker = RemoteMediaSession(MediaWorkerConnection(host="root@worker.example"))
    run = AsyncMock(return_value=b"{}")
    monkeypatch.setattr(worker, "_run", run)
    await worker._command(action)
    command = run.call_args.args
    assert command[0] == "ssh"
    assert "StrictHostKeyChecking=yes" in command
    shell = command[-1]
    for expected in ["MemoryMax=2048M", "MemorySwapMax=0", "CPUQuota=100%", "TasksMax=32",
                     "KillMode=control-group", "RuntimeMaxSec=3600", "flock -w 3600"]:
        assert expected in shell
    assert "api_key" not in shell and "OSS" not in shell


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_session_cleans_remote_job_on_failure_or_cancellation(monkeypatch, cancel):
    worker = RemoteMediaSession(MediaWorkerConnection(host="worker.example"))
    command = AsyncMock(return_value=b"{}")
    monkeypatch.setattr(worker, "_command", command)
    error_type = asyncio.CancelledError if cancel else RemoteMediaError
    with pytest.raises(error_type):
        async with worker:
            raise error_type()
    assert [call.args[0] for call in command.call_args_list] == ["create", "cleanup"]


@pytest.mark.asyncio
async def test_transfers_only_manifest_files_and_preserves_order(monkeypatch, tmp_path):
    worker = RemoteMediaSession(MediaWorkerConnection(host="worker.example"))
    source = tmp_path / "input.mov"
    source.write_bytes(b"video")
    transfers = []

    async def run(*args, **_kwargs):
        transfers.append(args)
        target = Path(args[-1])
        if str(target).endswith("model.mov"):
            target.write_bytes(b"video")
        elif "-r" in args:
            (target / "scene-001.mp4").write_bytes(b"a")
            (target / "scene-002.mp4").write_bytes(b"b")
        return b""

    monkeypatch.setattr(worker, "_run", run)
    command = AsyncMock(side_effect=[
        json.dumps({"filename": "model.mov", "size_bytes": 5}).encode(),
        json.dumps({"scenes": [{"filename": f"scene-{n:03d}.mp4", "duration_seconds": n * 4} for n in (1, 2)]}).encode(),
    ])
    monkeypatch.setattr(worker, "_command", command)
    model = await worker.prepare(source, tmp_path / "model-input", max_bytes=35_000_000)
    paths, durations = await worker.split(tmp_path / "scenes")
    assert model.read_bytes() == b"video"
    assert [p.read_bytes() for p in paths] == [b"a", b"b"]
    assert durations == [4, 8]
    assert transfers[0][-1].endswith("source.mov")
    assert "-r" in transfers[-1]


@pytest.mark.asyncio
async def test_cancel_kills_local_ssh_process(monkeypatch):
    worker = RemoteMediaSession(MediaWorkerConnection(host="worker.example"))
    created = asyncio.Event()
    real_create = asyncio.create_subprocess_exec
    processes = []

    async def create(*args, **kwargs):
        process = await real_create(*args, **kwargs)
        processes.append(process)
        created.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    task = asyncio.create_task(worker._run(sys.executable, "-c", "import time; time.sleep(30)"))
    await created.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None


@pytest.mark.asyncio
async def test_local_mode_remains_default(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "REMAKE_MEDIA_SSH_HOST", "")
    async with media_session() as worker:
        assert worker is None


@pytest.mark.asyncio
async def test_timeout_kills_transport_and_surfaces_worker_failure(monkeypatch):
    from unittest.mock import Mock
    process = Mock(returncode=None)
    process.communicate = AsyncMock(side_effect=[TimeoutError(), (b"", b"")])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    worker = RemoteMediaSession(MediaWorkerConnection(host="worker.example"))
    with pytest.raises(RemoteMediaError, match="超时"):
        await worker._run("ssh")
    process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_rejects_oversize_remote_artifact_before_downloading(monkeypatch, tmp_path):
    worker = RemoteMediaSession(MediaWorkerConnection(host="worker.example"))
    transfers = AsyncMock(return_value=b"")
    monkeypatch.setattr(worker, "_run", transfers)
    monkeypatch.setattr(worker, "_command", AsyncMock(return_value=b'{"filename":"model.mp4","size_bytes":35000001}'))
    with pytest.raises(RemoteMediaError, match="大小上限"):
        await worker.prepare(tmp_path / "source.mp4", tmp_path, max_bytes=35_000_000)
    assert transfers.call_count == 1  # Source upload only, no oversized response download.


@pytest.mark.parametrize("auth_enabled", [False, True])
@pytest.mark.parametrize("provider", ["password", "qiling"])
@pytest.mark.parametrize("host", ["", "root@worker.example"])
def test_configured_host_selects_remote_worker_for_any_login_method(monkeypatch, auth_enabled, provider, host):
    from config import settings
    from contextlib import nullcontext

    monkeypatch.setattr(settings, "AUTH_ENABLED", auth_enabled)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", provider)
    monkeypatch.setattr(settings, "REMAKE_MEDIA_SSH_HOST", host)
    worker = media_session()
    if host:
        assert isinstance(worker, RemoteMediaSession)
        assert worker.connection.host == host
        assert worker.connection.memory_mb == settings.REMAKE_MEDIA_MEMORY_MB
    else:
        assert isinstance(worker, nullcontext)
