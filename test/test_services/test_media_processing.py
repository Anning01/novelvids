import json
import subprocess
import tarfile
from pathlib import Path

import pytest
from pydantic import ValidationError


def test_command_bundle_rewrites_concat_and_filter_dependencies(tmp_path):
    from services.media_processing import CommandBundle
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'video')
    manifest = tmp_path / 'concat.txt'
    manifest.write_text("file 'source.mp4'\n")
    subtitles = tmp_path / 'captions.ass'
    subtitles.write_text('subtitle content')
    output = tmp_path / 'result.mp4'
    with CommandBundle(['ffmpeg', '-f', 'concat', '-i', str(manifest), '-vf',
                        f"ass=filename='{subtitles}'", str(output)], extra_files=[subtitles]) as bundle:
        spec = bundle.spec
        assert str(tmp_path) not in json.dumps(spec.model_dump())
        assert not output.exists()
        with tarfile.open(bundle.archive) as archive:
            bundled = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
        rewritten = bundled[spec.arguments[spec.arguments.index('-i') + 1]].decode()
        assert 'source.mp4' not in rewritten
        assert any(v == b'video' for v in bundled.values())
        assert spec.outputs == [spec.arguments[-1]]


@pytest.mark.parametrize('values', [
    {'program': 'sh', 'arguments': []},
    {'program': 'ffmpeg', 'arguments': [], 'outputs': ['../outside.mp4']},
    {'program': 'ffprobe', 'arguments': [], 'outputs': ['/etc/passwd']},
])
def test_worker_spec_rejects_commands_and_output_traversal(values):
    from schemas.media_processing import MediaProcessSpec
    with pytest.raises(ValidationError):
        MediaProcessSpec.model_validate(values)


def test_worker_extract_rejects_symlinks_and_traversal(tmp_path):
    from services.media_worker import unpack
    import io
    archive = tmp_path / 'input.tar'
    with tarfile.open(archive, 'w') as tar:
        entry = tarfile.TarInfo('../outside')
        entry.size = 1
        tar.addfile(entry, io.BytesIO(b'x'))
    with pytest.raises(ValueError):
        unpack(archive, tmp_path / 'job')
    assert not (tmp_path / 'outside').exists()


def test_configured_worker_failure_never_runs_local_ffmpeg(monkeypatch, tmp_path):
    from config import settings
    from services import media_processing as media
    from services.remake.remote_media import RemoteMediaError
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', 'worker.invalid')
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', True)
    async def fail(*args, **kwargs):
        raise RemoteMediaError('worker unavailable')
    monkeypatch.setattr(media, '_remote', fail)
    monkeypatch.setattr(media.subprocess, 'run', lambda *a, **k: pytest.fail('local process started'))
    with pytest.raises(RemoteMediaError):
        media.run_media(['ffmpeg', '-i', str(tmp_path / 'source.mp4'), str(tmp_path / 'out.mp4')])


def test_local_processing_keeps_original_command_and_does_not_acquire_slots(monkeypatch):
    from config import settings
    from services import media_processing as media
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', '')
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', False)
    calls = []
    monkeypatch.setattr(media.subprocess, 'run', lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    command = ['ffmpeg', '-i', 'source.mp4', 'result.mp4']
    with media._slots:
        media.run_media(command)
    assert calls == [command]


def test_worker_host_alone_does_not_enable_generic_offload(monkeypatch):
    from config import settings
    from services import media_processing as media
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', False)
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', 'worker.invalid')
    calls = []
    monkeypatch.setattr(media.subprocess, 'run', lambda command, **kwargs:
        calls.append(command) or subprocess.CompletedProcess(command, 0))
    command = ['ffmpeg', '-i', 'source.mp4', 'out.mp4']
    with media._slots:
        media.run_media(command)
    assert calls == [command]


def test_remote_processing_is_disabled_without_explicit_deployment_setting():
    import os
    import sys
    env = dict(os.environ)
    env.pop('MEDIA_PROCESSING_REMOTE_ENABLED', None)
    # dotenv must not silently enable a server-only setting in default installations.
    env['PYTHON_DOTENV_DISABLED'] = '1'
    result = subprocess.run([sys.executable, '-c',
        'from config import settings; assert settings.MEDIA_PROCESSING_REMOTE_ENABLED is False'],
        env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_local_async_processing_bypasses_remote_limits_and_preserves_arguments(monkeypatch):
    from config import settings
    from services import media_processing as media
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', False)
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', 'worker.invalid')
    from unittest.mock import AsyncMock
    execute = AsyncMock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(media, '_local_async', execute)
    command = ['ffmpeg', '-threads', '4', '-i', 'source.mp4', 'out.mp4']
    with media._slots:
        await media.run_media_async(command, timeout=30)
    execute.assert_awaited_once_with(command, {'timeout': 30})


def test_local_image_derivatives_bypass_remote_limits(monkeypatch):
    from config import settings
    from services import media_processing as media
    import services.media_images
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', False)
    monkeypatch.setattr(services.media_images, 'render_derivatives', lambda value: {'thumbnail': value})
    with media._slots:
        assert media.image_derivatives(b'image') == {'thumbnail': b'image'}


def test_enabled_worker_without_connection_fails_instead_of_running_locally(monkeypatch):
    from config import settings
    from services import media_processing as media
    from services.remake.remote_media import RemoteMediaError
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', True)
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', '')
    with pytest.raises(RemoteMediaError):
        media.run_media(['ffmpeg', '-i', 'source.mp4', 'out.mp4'])


@pytest.fixture
def staged_worker(monkeypatch, tmp_path):
    import shutil
    from types import SimpleNamespace
    from config import settings
    from services.remake import remote_media
    from services.media_worker import execute
    jobs = tmp_path / 'worker'
    jobs.mkdir()
    class Session:
        connection = SimpleNamespace(host='worker.invalid')
        async def __aenter__(self):
            from uuid import uuid4
            self.work = jobs / uuid4().hex
            self.work.mkdir()
            return self
        async def __aexit__(self, *args):
            shutil.rmtree(self.work)
        async def _run(self, *command):
            source, target = command[-2:]
            shutil.copyfile(source.removeprefix('worker.invalid:'), target.removeprefix('worker.invalid:'))
            return b''
        async def _command(self, action):
            assert action == 'process'
            execute(self.work)
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', 'worker.invalid')
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', True)
    monkeypatch.setattr(remote_media, 'media_session', Session)
    return jobs


@pytest.mark.asyncio
async def test_staged_worker_preserves_real_video_concat_and_probe(staged_worker, tmp_path):
    from services.media_processing import run_media_async
    sources = []
    for color in ('red', 'blue'):
        path = tmp_path / f'{color}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        f'color={color}:s=32x32:r=10:d=0.5', str(path)], check=True)
        sources.append(path)
    concat = tmp_path / 'concat.txt'
    concat.write_text(''.join(f"file '{path.name}'\n" for path in sources))
    output = tmp_path / 'output.mp4'
    await run_media_async(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '1',
                           '-i', str(concat), '-c', 'copy', str(output)], check=True)
    result = await run_media_async(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                                   '-of', 'json', str(output)], check=True, text=True)
    probe = json.loads(result.stdout)
    assert float(probe['format']['duration']) == 1
    assert probe['streams'][0]['width'] == 32
    assert not list(staged_worker.iterdir())


@pytest.mark.asyncio
async def test_failed_remote_command_preserves_existing_output(staged_worker, tmp_path):
    from services.media_processing import run_media_async
    source, output = tmp_path / 'invalid.mp4', tmp_path / 'previous.mp4'
    source.write_bytes(b'not a valid video')
    output.write_bytes(b'previous completed video')
    with pytest.raises(subprocess.CalledProcessError):
        await run_media_async(['ffmpeg', '-v', 'error', '-y', '-i', str(source), str(output)], check=True)
    assert output.read_bytes() == b'previous completed video'
    assert not list(staged_worker.iterdir())


def test_staged_worker_preserves_image_derivatives(staged_worker):
    import cv2
    import numpy as np
    from services.media_processing import image_derivatives
    from services.media_images import render_derivatives
    _, encoded = cv2.imencode('.png', np.full((32, 32, 3), 123, dtype=np.uint8))
    original = encoded.tobytes()
    assert image_derivatives(original) == render_derivatives(original)
    assert not list(staged_worker.iterdir())


@pytest.mark.asyncio
async def test_staged_worker_transfers_subtitles_and_symlinked_fonts(staged_worker, tmp_path):
    from services.media_processing import run_media_async
    from services.video_editor.render import subtitle_font
    font = subtitle_font()
    fonts = tmp_path / 'fonts'
    fonts.mkdir()
    (fonts / font.name).symlink_to(font)
    # A real ASS filter opens both the transferred subtitle and font files.
    subtitle = tmp_path / 'subtitle.ass'
    subtitle.write_text('[Script Info]\nScriptType: v4.00+\nPlayResX: 64\nPlayResY: 64\n'
        '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
        'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
        'Style: Default,sans-serif,12,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,2,2,2,1\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        'Dialogue: 0,0:00:00.00,0:00:00.50,Default,,0,0,0,,Hello\n')
    output = tmp_path / 'captioned.mp4'
    await run_media_async(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=blue:s=64x64:r=10:d=0.5',
        '-vf', f"ass=filename='{subtitle}':fontsdir='{fonts}'", str(output)],
        extra_files=[subtitle, fonts], check=True)
    assert output.stat().st_size > 0
    assert not list(staged_worker.iterdir())


@pytest.mark.asyncio
async def test_concurrent_media_jobs_are_serialized_before_staging(monkeypatch, tmp_path):
    import asyncio
    from config import settings
    from services import media_processing as media
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', 'worker.invalid')
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', True)
    active = peak = 0
    async def remote(bundle):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.02)
        active -= 1
        return {'returncode': 0, 'stdout': '', 'stderr': ''}
    monkeypatch.setattr(media, '_remote', remote)
    await asyncio.gather(*(media.run_media_async(['ffprobe', 'input.mp4']) for _ in range(4)))
    assert peak == 1


@pytest.mark.asyncio
async def test_completed_video_uploads_file_stream_without_reading_entire_video(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import controllers.video as controller
    import services.oss
    import services.video.duration
    class Response:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_bytes(self, **kwargs):
            for _ in range(20):
                yield b'x' * 8192
    class Client(Response):
        def __init__(self, **kwargs): pass
        def stream(self, *args, **kwargs): return Response()
    uploaded = []
    async def put_file(key, source, content_type):
        assert isinstance(source, Path) and source.stat().st_size == 20 * 8192
        uploaded.append((key, content_type))
    provider = SimpleNamespace(enabled=True, put_file=put_file,
        put_bytes=AsyncMock(side_effect=AssertionError('whole-file upload used')))
    monkeypatch.setattr(services.oss, 'oss', provider)
    monkeypatch.setattr(controller.settings, 'MEDIA_PATH', str(tmp_path))
    monkeypatch.setattr(controller.settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', True)
    monkeypatch.setattr(controller.httpx, 'AsyncClient', Client)
    monkeypatch.setattr(controller.video_poster_service, 'extract_file_and_store', AsyncMock(return_value={}))
    monkeypatch.setattr(services.video.duration, 'measure_video_duration', lambda path: 1.0)
    await controller._download_video('https://example.invalid/video.mp4', 987)
    assert uploaded and uploaded[0][1] == 'video/mp4'
    provider.put_bytes.assert_not_called()
    assert not (tmp_path / 'videos/987.mp4').exists()


@pytest.mark.asyncio
async def test_default_generated_upload_keeps_bytes_only_provider_compatibility(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import controllers.video as controller
    import services.oss
    source = tmp_path / 'video.mp4'
    source.write_bytes(b'video')
    provider = SimpleNamespace(put_bytes=AsyncMock())
    monkeypatch.setattr(services.oss, 'oss', provider)
    monkeypatch.setattr(controller.settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', False)
    await controller._upload_generated_file('uploads/video.mp4', source, 'video/mp4')
    provider.put_bytes.assert_awaited_once_with('uploads/video.mp4', b'video', 'video/mp4')


@pytest.mark.asyncio
async def test_remote_cancellation_releases_slot_and_cleans_session(monkeypatch):
    import asyncio
    from config import settings
    from services import media_processing as media
    monkeypatch.setattr(settings, 'REMAKE_MEDIA_SSH_HOST', 'worker.invalid')
    monkeypatch.setattr(settings, 'MEDIA_PROCESSING_REMOTE_ENABLED', True)
    started = asyncio.Event()
    cleaned = []
    async def wait(*args, **kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            cleaned.append(True)
    monkeypatch.setattr(media, '_remote', wait)
    task = asyncio.create_task(media.run_media_async(['ffmpeg', 'out.mp4']))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned
    assert media._slots.acquire(blocking=False)
    media._slots.release()


def test_active_media_io_does_not_depend_on_shared_executor_capacity():
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from services.media_processing import media_file_io
    # Simulate sync callers filling the application's normal thread pool.
    async def run():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        waiting = threading.Event()
        occupied = loop.run_in_executor(None, waiting.wait)
        try:
            assert await asyncio.wait_for(media_file_io(lambda: 42), timeout=1) == 42
        finally:
            waiting.set()
            await occupied
    asyncio.run(run())
