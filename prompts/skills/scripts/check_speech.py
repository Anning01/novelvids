"""Check storyboard voice windows and per-speaker pacing (Python standard library)."""

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

TIMELINE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*[-–—~]\s*(\d+(?:\.\d+)?)\s*s?\s*[:：]")
WORDS = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*")
PAUSES = re.compile(r"[，,。.!！?？;；:：、…]+")


def split_voice_track(value):
    """Return speaker/delivery prefix and verbatim speech, ignoring colons inside cues."""
    match = TIMELINE.match(value)
    start = match.end() if match else 0
    depth = 0
    for index in range(start, len(value)):
        char = value[index]
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(0, depth - 1)
        elif char in ":：" and depth == 0:
            return value[:index + 1], value[index + 1:]
    return value, ""


def speaker_aliases(entities):
    owners = {}
    names = set()
    for entity in entities:
        if entity.get("asset_type", "人物") != "人物":
            continue
        name = entity["name"].partition("#")[0]
        names.add(name)
        for alias in entity.get("aliases", []):
            owners.setdefault(alias, set()).add(name)
    return {alias: next(iter(matches)) for alias, matches in owners.items()
            if alias not in names and len(matches) == 1}


@dataclass(frozen=True)
class VoiceLine:
    start: float
    end: float
    speaker: str
    cues: tuple
    text: str


def parse_line(line):
    match = TIMELINE.match(line)
    prefix, text = split_voice_track(line)
    if not match or not any(c.isalnum() for c in text):
        raise ValueError("人声条目必须包含时间轴、说话者和完整台词正文")
    label = prefix[match.end():-1].strip()
    speaker = re.split(r"[（(]", label, maxsplit=1)[0].strip().removeprefix("@{").removesuffix("}")
    if not speaker:
        raise ValueError("人声条目必须包含时间轴、说话者和完整台词正文")
    cues = tuple(part.strip().casefold() for group in re.findall(r"[（(]([^（）()]*)[）)]", label)
                 for part in re.split(r"[,，、;；]", group))
    return VoiceLine(float(match[1]), float(match[2]), speaker, cues, text)


def measure(text, policy, factor=1.0):
    words = len(WORDS.findall(text))
    chars = sum(c.isalnum() for c in WORDS.sub("", text))
    pause = len(PAUSES.findall(text)) * policy["pause_seconds"]
    cmin, cmax = policy["characters_per_second"]
    wmin, wmax = policy["words_per_second"]
    typical = chars / ((cmin + cmax) / 2) + words / ((wmin + wmax) / 2)
    minimum = (chars / cmax + words / wmax) / factor + pause
    maximum = (chars / cmin + words / wmin) / factor + pause + policy["slack_seconds"]
    return minimum, maximum, typical, pause


def delivery_factor(line, continuity):
    if continuity and any(cue in continuity["slow_cues"] for cue in line.cues):
        return continuity["slow_rate_factor"]
    return 1.0


def pace_issues(shots, policy, aliases=None):
    """Return (list index, issue) pairs, comparing only long-enough normal lines."""
    continuity = policy.get("continuity")
    if not continuity:
        return []
    aliases = aliases or {}
    baselines = {}
    previous = {}
    issues = []
    ratio = continuity["max_rate_ratio"]
    for index, shot in enumerate(shots):
        number = shot["sequence"]
        lines = sorted((parse_line(raw) for field in ("narration", "dialogue")
                        for raw in shot.get(field, [])), key=lambda item: item.start)
        latest = {}
        for line in lines:
            if delivery_factor(line, continuity) != 1:
                continue
            minimum, maximum, typical, pause = measure(line.text, policy)
            window = line.end - line.start
            if typical < continuity["min_sample_seconds"] or not minimum - .001 <= window <= maximum + .001:
                continue
            name = line.speaker.partition("#")[0]
            name = aliases.get(name, name)
            # Normalize mixed Chinese/Latin lines to the same reference speed.
            rate = typical / (window - pause)
            base_index, base_number, base_rate = baselines.setdefault(name, (index, number, rate))
            if index == base_index:
                # An exceptionally varied opening shot still has one clear baseline.
                if max(rate, base_rate) <= min(rate, base_rate) * ratio:
                    latest[name] = (number, rate)
                continue
            references = [(base_number, base_rate)]
            if name in previous:
                references.append(previous[name])
            lo, hi = minimum, maximum
            failed_reference = None
            for reference_number, reference_rate in references:
                target = typical / reference_rate
                low, high = pause + target / ratio, pause + target * ratio
                lo, hi = max(lo, low), min(hi, high)
                if window < low - .001 or window > high + .001:
                    failed_reference = reference_number
            if failed_reference is None:
                latest[name] = (number, rate)
            else:
                issues.append((index, (name, failed_reference, number, line.start, line.end, window, lo, hi)))
        previous.update(latest)
    return issues


PACE_ERROR = "角色 {p0} 相对第 {p1} 镜的普通语速发生偏移。第 {p2} 镜 {p3}–{p4} 秒的台词分配了 {p5} 秒，请调整为 {p6}–{p7} 秒，保留原话。"


def issue_values(issue):
    speaker, base, number, *seconds = issue
    return dict(zip(("p0", "p1", "p2", "p3", "p4", "p5", "p6", "p7"),
                    (speaker, base, number, *(f"{s:.2f}" for s in seconds))))


def audit(board, policy):
    errors = []
    shots = board["shots"]
    if not isinstance(shots, list) or not shots:
        raise ValueError("shots must be a non-empty list")
    for shot in shots:
        number = shot["sequence"]
        duration = float(str(shot["duration"]).removesuffix("s"))
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"Invalid duration for shot {number}")
        windows = []
        for field in ("dialogue", "narration"):
            for raw in shot.get(field, []):
                line = parse_line(raw)
                windows.append((line.start, line.end))
                factor = delivery_factor(line, policy.get("continuity"))
                minimum, maximum, _, _ = measure(line.text, policy, factor)
                if not (0 <= line.start < line.end <= duration + .001 and
                        minimum - .001 <= line.end - line.start <= maximum + .001):
                    errors.append(f"第 {number} 镜 {line.speaker} {line.start:g}–{line.end:g}s："
                                  f"检查镜内边界，台词时长应为 {minimum:.2f}–{maximum:.2f}s。")
        windows.sort()
        if any(a[1] > b[0] + .001 for a, b in zip(windows, windows[1:])):
            errors.append(f"第 {number} 镜：人声重叠")
    for _, issue in pace_issues(shots, policy, speaker_aliases(board.get("entities", []))):
        errors.append(PACE_ERROR.format(**issue_values(issue)))
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storyboard", type=Path, help="JSON with shots in playback order")
    parser.add_argument("--contract", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    default_contract = root / "references/storyboard_contract.json"
    if not default_contract.is_file():
        default_contract = root / "novelvids-storyboard/references/storyboard_contract.json"
    try:
        board = json.loads(args.storyboard.read_text(encoding="utf-8"))
        policy = json.loads((args.contract or default_contract).read_text(encoding="utf-8"))["speech_timing"]
        errors = audit(board, policy)
    except (ValueError, OSError, KeyError, TypeError, ZeroDivisionError) as error:
        parser.exit(2, f"输入无效：{error}\n")
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print(f"通过：{len(board['shots'])} 镜的人声时间窗与跨镜语速。")
