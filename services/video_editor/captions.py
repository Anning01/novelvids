"""Readable caption segmentation using word timestamps when available."""
from dataclasses import dataclass
import math
import unicodedata

from utils.subtitle_text import CAPTION_BOUNDARY_MARKS


@dataclass(frozen=True)
class CaptionSegment:
    start: float
    end: float
    text: str


def _seconds(value, default: float) -> float:
    try:
        result = float(value) / 1000
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def split_utterance(item: dict, max_units: float = 20, max_seconds: float = 5) -> list[CaptionSegment]:
    if not isinstance(item, dict):
        return []
    text = item.get('text')
    if not isinstance(text, str) or not text.strip():
        return []
    text = text.strip()
    start = max(0, _seconds(item.get('start_time'), 0))
    end = max(start + .1, _seconds(item.get('end_time'), start + .1))
    timings: list[tuple[float, float] | None] = [None] * len(text)
    cursor = 0
    for word in item.get('words') or []:
        if not isinstance(word, dict) or not isinstance(word.get('text'), str):
            continue
        value = word['text'].strip()
        index = text.find(value, cursor) if value else -1
        a, b = _seconds(word.get('start_time'), -1), _seconds(word.get('end_time'), -1)
        if index < 0 or not start <= a < b <= end + .001:
            continue
        for i in range(len(value)):
            timings[index + i] = (a + (b-a)*i/len(value), a + (b-a)*(i+1)/len(value))
        cursor = index + len(value)
    has_word_times = any(value is not None for value in timings)
    # Missing punctuation/word timestamps interpolate only between known neighbors.
    index, previous = 0, start
    while index < len(text):
        if timings[index] is not None:
            a, b = timings[index]
            timings[index] = (max(previous, a), max(previous, b))
            previous = timings[index][1]
            index += 1
            continue
        stop = index
        while stop < len(text) and timings[stop] is None:
            stop += 1
        following = max(previous, timings[stop][0] if stop < len(text) else end)
        span = stop - index
        for i in range(index, stop):
            timings[i] = (previous + (following-previous)*(i-index)/span, previous + (following-previous)*(i-index+1)/span)
        previous = following
        index = stop
    pieces: list[CaptionSegment] = []
    cursor = 0
    punctuation = CAPTION_BOUNDARY_MARKS + '！？；!?;'
    while cursor < len(text):
        stop, units, last_space = cursor, 0.0, -1
        while stop < len(text):
            char = text[stop]
            units += 1 if unicodedata.east_asian_width(char) in {'W', 'F'} else .55
            if char.isspace():
                last_space = stop
            stop += 1
            natural_break = char in punctuation and (units >= 6 or char in '。！？.!?')
            elapsed = timings[stop-1][1] - timings[cursor][0]
            if natural_break:
                break
            if units >= max_units or elapsed >= max_seconds:
                if stop < len(text) and text[stop-1].isascii() and text[stop-1].isalnum() and text[stop].isascii() and text[stop].isalnum():
                    if last_space > cursor:
                        stop = last_space + 1
                    else:
                        while stop < len(text) and text[stop].isascii() and text[stop].isalnum():
                            stop += 1
                break
        left, right = cursor, stop
        while left < right and (text[left].isspace() or text[left] in CAPTION_BOUNDARY_MARKS):
            left += 1
        while right > left and (text[right-1].isspace() or text[right-1] in punctuation):
            right -= 1
        if right > left:
            a, b = timings[left][0], timings[right-1 if has_word_times else stop-1][1]
            pieces.append(CaptionSegment(a, max(a + 1/60, b), text[left:right]))
        cursor = stop
    return pieces
