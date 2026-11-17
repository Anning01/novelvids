"""Parse scene boundaries for blocking-map generation."""
import re

_SCENE_HEADING = re.compile(
    r"^[^\S\n]*(?:#{1,6}[^\S\n]+)?(?:\*\*)?(?P<episode>\d+)[ \t]*[-－—–][ \t]*(?P<scene>\d+)"
    r"(?=(?:\*\*)?[^\S\n]+\S)", re.MULTILINE,
)


def screenplay_sections(text: str) -> list[tuple[str | None, str]]:
    headings = list(_SCENE_HEADING.finditer(text))
    if not headings:
        return [(None, text)]
    sections = []
    for index, heading in enumerate(headings):
        start = heading.start() if index else 0  # Keep the episode title and opening notes.
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections.append((f"{heading['episode']}-{heading['scene']}", text[start:end].strip()))
    return sections
