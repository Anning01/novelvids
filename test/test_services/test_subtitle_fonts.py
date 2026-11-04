import hashlib

import httpx
import pytest
from pydantic import ValidationError

from schemas.video_edit import SubtitleClip
from services.video_editor.fonts import cached_subtitle_font
from services.video_editor.subtitles import subtitle_ass_many
from utils.subtitle_fonts import SUBTITLE_FONTS, subtitle_font_options


def test_picker_catalog_matches_supported_fonts_and_ass_export():
    assert 10 <= len(SUBTITLE_FONTS) <= 20
    base = {'id': 's', 'type': 'subtitle', 'start': 0, 'duration': 1, 'text': '，字体。'}
    clips = [SubtitleClip(**base, font=option['value']) for option in subtitle_font_options()]
    output = subtitle_ass_many(clips, 1920, 1080)
    for font in SUBTITLE_FONTS.values():
        assert f",{font['family']}," in output
    assert output.count('}字体\n') == len(clips)
    with pytest.raises(ValidationError):
        SubtitleClip(**base, font='../outside')


@pytest.mark.asyncio
async def test_download_checks_integrity_and_reuses_cache(tmp_path, monkeypatch):
    payload = b'font example'
    entry = SUBTITLE_FONTS['source-han-serif']
    monkeypatch.setattr('config.settings.CHAPTER_EXPORT_PATH', str(tmp_path))
    monkeypatch.setitem(SUBTITLE_FONTS, 'source-han-serif', {**entry, 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
    client = httpx.AsyncClient
    sent = []
    def respond(request):
        sent.append(request.url)
        return httpx.Response(200, content=payload if len(sent) > 1 else b'wrong bytes!')
    monkeypatch.setattr('services.video_editor.fonts.httpx.AsyncClient',
                        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs))
    with pytest.raises(ValueError):
        await cached_subtitle_font('source-han-serif')
    assert not list(tmp_path.glob('.subtitle-fonts/*'))
    path = await cached_subtitle_font('source-han-serif')
    assert path.read_bytes() == payload
    assert await cached_subtitle_font('source-han-serif') == path
    assert len(sent) == 2 and sent[0].host == 'raw.githubusercontent.com'
