"""Pinned subtitle font metadata shared by validation, the picker and exports."""
import json
from pathlib import Path

_catalog = json.loads((Path(__file__).resolve().parents[1] / 'seeds/subtitle_fonts.json').read_text(encoding='utf-8'))
FONT_REVISION = _catalog['revision']
SUBTITLE_FONTS = {font['value']: font for font in _catalog['fonts']}


def subtitle_font_options() -> list[dict[str, str]]:
    return [{'value': 'sans', 'label': '系统中文黑体'}, *(
        {key: font[key] for key in ('value', 'label')} for font in SUBTITLE_FONTS.values()
    )]
