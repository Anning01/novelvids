"""Subtitle boundary punctuation rules."""

CAPTION_BOUNDARY_MARKS = '，。,.．、'


def clean_caption_edges(text: str) -> str:
    start, end = 0, len(text)
    while start < end and (text[start].isspace() or text[start] in CAPTION_BOUNDARY_MARKS):
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in CAPTION_BOUNDARY_MARKS):
        end -= 1
    return text[start:end]
