import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import subprocess

import httpx
import pytest

from config import settings
from services.video_enhancement.media import export_media, file_digest, inspect_media


def fixture_video(path, *, hd=False, fps=24, seconds='0.5', size=None):
    size=size or ('1920x1080' if hd else '480x270')
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color=c=blue:s={size}:r={fps}',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=32000','-t',seconds,'-c:v','libx264','-preset','ultrafast',
        '-c:a','aac',str(path)],check=True,capture_output=True)


@pytest.mark.asyncio
async def test_real_media_compose_is_immutable_and_saved_atomically(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'MEDIA_PATH',str(tmp_path))
    monkeypatch.setattr(settings,'CHAPTER_EXPORT_PATH',str(tmp_path.with_name(tmp_path.name+'-exports')))
    source=tmp_path/'clip.mp4';fixture_video(source)
    export=SimpleNamespace(id=99,team_id=None,manifest=[{'ref':'/media/clip.mp4','sha256':file_digest(source)}])
    result=await export_media.compose(export)
    saved=export_media.local_path(result['ref'])
    assert not saved.is_relative_to(tmp_path)
    assert saved.is_file() and file_digest(saved)==result['sha256']
    assert inspect_media(saved).audio_streams
    source.write_bytes(b'changed')
    with pytest.raises(ValueError):await export_media.compose(export)
    assert file_digest(saved)==result['sha256']


@pytest.mark.asyncio
async def test_enhanced_save_verifies_specs_and_keeps_original_audio(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'MEDIA_PATH',str(tmp_path))
    monkeypatch.setattr(settings,'CHAPTER_EXPORT_PATH',str(tmp_path.with_name(tmp_path.name+'-exports')))
    source=tmp_path/'source.mp4';fixture_video(source)
    enhanced=tmp_path/'enhanced.mp4';fixture_video(enhanced,hd=True)
    export=SimpleNamespace(id=100,team_id=None,provider_result={'result':{'video_url':'https://download.example/result.mp4'}},
        source_probe=inspect_media(source).model_dump(mode='json'),source_media_ref='/media/source.mp4',source_sha256=file_digest(source))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r:httpx.Response(200,content=enhanced.read_bytes()))) as http:
        result=await export_media.save_enhanced(export,http)
    output=export_media.local_path(result['ref'])
    assert output.is_file() and result['probe']['height']==1080
    def audio(path):
        return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','adts','-'])
    assert audio(output)==audio(source)


@pytest.mark.asyncio
async def test_wrong_output_dimensions_never_publish_an_enhanced_file(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'MEDIA_PATH',str(tmp_path))
    monkeypatch.setattr(settings,'CHAPTER_EXPORT_PATH',str(tmp_path.with_name(tmp_path.name+'-exports')))
    source=tmp_path/'source.mp4';fixture_video(source)
    export=SimpleNamespace(id=101,team_id=None,provider_result={'result':{'video_url':'https://download.example/result.mp4'}},
        source_probe=inspect_media(source).model_dump(mode='json'),source_media_ref='/media/source.mp4',source_sha256=file_digest(source))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r:httpx.Response(200,content=source.read_bytes()))) as http:
        with pytest.raises(ValueError):await export_media.save_enhanced(export,http)
    assert not export_media.local_path('/media/exports/101/1080p.mp4').exists()


def test_export_directory_cannot_be_exposed_under_public_media(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path/'exports'))
    with pytest.raises(ValueError):
        export_media.local_path('/media/exports/1/source.mp4')
    with pytest.raises(ValueError):
        export_media.input_url('/media/exports/1/source.mp4', 'https://public.example')


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['corrupt', 'fps', 'duration', 'aspect'])
async def test_invalid_outputs_are_rejected_without_publishing(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path))
    monkeypatch.setattr(settings, 'CHAPTER_EXPORT_PATH', str(tmp_path.with_name(tmp_path.name+'-private')))
    source = tmp_path/'source.mp4'
    fixture_video(source)
    output = tmp_path/'output.mp4'
    if invalid == 'corrupt':
        output.write_bytes(b'truncated or non-video provider response')
    else:
        fixture_video(output, hd=True, fps=30 if invalid == 'fps' else 24,
            seconds='1' if invalid == 'duration' else '0.5', size='1080x1920' if invalid == 'aspect' else None)
    export = SimpleNamespace(id=102, team_id=None,
        provider_result={'result':{'video_url':'https://download.example/result.mp4'}},
        source_probe=inspect_media(source).model_dump(mode='json'), source_media_ref='/media/source.mp4', source_sha256=file_digest(source))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r:httpx.Response(200,content=output.read_bytes()))) as http:
        with pytest.raises(ValueError):
            await export_media.save_enhanced(export,http)
    assert not export_media.local_path('/media/exports/102/1080p.mp4').exists()
