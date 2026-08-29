"""文件夹视频集数解析与批次一致性校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from exceptions.remake import RemakeError


_EPISODE_PATTERNS = (
    re.compile(r"第\s*(\d+)\s*[集话]", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])EP\s*0*(\d+)(?!\d)", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])E\s*0*(\d+)(?!\d)", re.IGNORECASE),
    re.compile(r"(?<!\d)0*(\d+)\s*集(?!\d)", re.IGNORECASE),
)


@dataclass(frozen=True)
class EpisodeBatchItem:
    filename: str
    episode_number: int
    value: Any


def parse_episode_number(filename: str) -> int:
    stem = Path(Path(filename).name).stem
    matches = {
        int(match.group(1))
        for pattern in _EPISODE_PATTERNS
        for match in pattern.finditer(stem)
        if match.group(1)
    }
    valid = {number for number in matches if 1 <= number <= 99999}
    if not valid:
        raise RemakeError(
            422,
            "REMAKE_EPISODE_MISSING",
            "视频文件名中缺少有效集数",
            context={"filename": Path(filename).name},
        )
    if len(valid) > 1 or matches != valid:
        raise RemakeError(
            422,
            "REMAKE_EPISODE_AMBIGUOUS",
            "视频文件名包含多个不同集数",
            context={
                "filename": Path(filename).name,
                "episode_numbers": sorted(matches),
            },
        )
    return next(iter(valid))


def validate_episode_batch(
    entries: Iterable[tuple[str, int, Any]],
) -> tuple[list[EpisodeBatchItem], list[int]]:
    items: list[EpisodeBatchItem] = []
    seen: dict[int, str] = {}
    for filename, claimed_episode, value in entries:
        parsed = parse_episode_number(filename)
        if parsed != claimed_episode:
            raise RemakeError(
                422,
                "REMAKE_SOURCE_MODE_MISMATCH",
                "客户端集数与服务端文件名解析结果不一致",
                context={
                    "filename": Path(filename).name,
                    "claimed_episode_number": claimed_episode,
                    "parsed_episode_number": parsed,
                },
            )
        if parsed in seen:
            raise RemakeError(
                409,
                "REMAKE_EPISODE_DUPLICATED",
                "文件夹中存在重复集数",
                context={
                    "episode_number": parsed,
                    "filenames": [seen[parsed], Path(filename).name],
                },
            )
        seen[parsed] = Path(filename).name
        items.append(EpisodeBatchItem(Path(filename).name, parsed, value))

    items.sort(key=lambda item: item.episode_number)
    if not items:
        return [], []
    present = {item.episode_number for item in items}
    missing = [
        number
        for number in range(items[0].episode_number, items[-1].episode_number + 1)
        if number not in present
    ]
    return items, missing


EPISODE_PATTERN_EXAMPLES = ("第12集", "第12话", "EP12", "E12", "12集")
