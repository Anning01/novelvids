"""Plain-text subtitle layout and ASS serialization shared by the export pipeline."""
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

from schemas.video_edit import SubtitleClip


@lru_cache(maxsize=1)
def subtitle_styles() -> list[dict]:
    return json.loads((Path(__file__).resolve().parents[2] / 'seeds/subtitle_styles.json').read_text(encoding='utf-8'))


def char_width(char: str, size: float) -> float:
    return size * (1 if unicodedata.east_asian_width(char) in {'W', 'F'} else .55)


def wrap_subtitle(text: str, width: int, font_size: float, letter_spacing: float = 0) -> str:
    limit = width * .88
    lines, line, used = [], '', 0.0
    for char in text.replace('\r', ''):
        advance = char_width(char, font_size) + (letter_spacing if line else 0)
        if char == '\n' or line and used + advance > limit:
            lines.append(line)
            line, used = '', 0
            if char == '\n':
                continue
            advance = char_width(char, font_size)
        if ord(char) >= 32 or char == '\t':
            line += char
            used += advance
    lines.append(line)
    return '\n'.join(lines)


def ass_color(color: str, opacity: float = 1) -> str:
    red, green, blue = color[1:3], color[3:5], color[5:7]
    return f'&H{round((1-opacity)*255):02X}{blue}{green}{red}'


def ass_time(seconds: float) -> str:
    ticks = round(seconds * 100)
    return f'{ticks//360000}:{ticks//6000%60:02}:{ticks//100%60:02}.{ticks%100:02}'


def escape_ass(text: str) -> str:
    # Backslashes and braces are literal user text, never ASS override instructions.
    return text.replace('\\', '\\' + '\u2060').replace('{', r'\{').replace('}', r'\}').replace('\t', '    ')


def subtitle_ass(clip: SubtitleClip, width: int, height: int) -> str:
    scale = height / 1080
    size, spacing = clip.font_size * scale, clip.letter_spacing * scale
    lines = wrap_subtitle(clip.text, width, size, spacing).split('\n')
    widths = [sum(char_width(c, size) for c in line) + max(0, len(line)-1)*spacing for line in lines]
    block_width = max(widths, default=0)
    line_height = size * 1.2 + clip.line_spacing * scale
    x = width * clip.x / 100
    if clip.align == 'left':
        x -= block_width / 2
    elif clip.align == 'right':
        x += block_width / 2
    top = height * (1 - clip.bottom / 100) - len(lines) * line_height
    alignment = {'left': 7, 'center': 8, 'right': 9}[clip.align]
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Text,sans-serif,{size:.5f},{ass_color(clip.color,clip.opacity)},{ass_color(clip.color,clip.opacity)},{ass_color(clip.stroke_color,clip.opacity)},{ass_color('#000000',clip.opacity)},{-int(clip.bold)},{-int(clip.italic)},{-int(clip.underline)},0,100,100,{spacing:.5f},0,1,{clip.stroke_width*scale:.5f},{clip.shadow*scale:.5f},{alignment},0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    for index, line in enumerate(lines):
        if line:
            position = f'{{\\an{alignment}\\pos({x:.5f},{top + index * line_height:.5f})}}'
            events.append(f'Dialogue: 0,{ass_time(clip.start)},{ass_time(clip.start+clip.duration)},Text,,0,0,0,,{position}{escape_ass(line)}')
    return header + '\n'.join(events) + '\n'
