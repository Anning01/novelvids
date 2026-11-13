from types import SimpleNamespace

import pytest
from config import settings
from fastapi import HTTPException

from services.storyboard.blocking_reference import blocking_source, provider_image
from prompts.storyboard_sheet_binding import blocking_rules, bind_blocking


@pytest.mark.asyncio
async def test_structured_plan_or_archived_image(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'MEDIA_PATH', str(tmp_path))
    scene = SimpleNamespace(id=5, prompt_params={'segments': [{}, {}], 'blocking_map': {
        'orientation': '北', 'assets': [{'name': '门', 'x': 88, 'y': 24}],
        'cameras': [{'x': 57, 'y': 94, 'target': '门'}]}})
    source = blocking_source(5, {}, scene.prompt_params)
    result = await provider_image(scene, source)
    assert (tmp_path / result.removeprefix('/media/')).read_bytes().startswith(b'\x89PNG')
    assert await provider_image(scene, source) == result
    assert blocking_source(5, None, {}) is None
    url = '/media/work-packages/' + ('a' * 64) + '.png'
    (tmp_path / "work-packages").mkdir()
    (tmp_path / url.removeprefix("/media/")).write_bytes(b"image")
    source = blocking_source(5, {'imported_media': [{'role': 'blocking', 'url': url}]}, scene.prompt_params)
    assert await provider_image(scene, source) == url
    with pytest.raises(HTTPException):
        await provider_image(scene, '/media/other.svg')


@pytest.mark.parametrize('language,model,word', [('zh', 'general', '机位'), ('zh', 'minimax_h3', 'camera'), ('en', 'wan_3', 'camera')])
def test_blocking_reference_is_inserted_once(language, model, word):
    rule = blocking_rules(language)[model]
    text = bind_blocking(rule['headings'][0] + '\nAction', rule, 'IMAGE')
    assert text.splitlines()[1].startswith('IMAGE') and word in text
    assert bind_blocking(text, rule, 'IMAGE') == text
