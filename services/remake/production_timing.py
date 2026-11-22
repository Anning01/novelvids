"""Keep frame-accurate source boundaries separate from whole-second generation requests."""
import math


def whole_second(seconds):
    return math.floor(seconds + 0.5)


def production_ranges(scenes, limit):
    """Use the fewest requests allowed by the cap; prefer nearby real edits."""
    if not 1 <= limit <= 30:
        raise ValueError("Generation shot limit must be between 1 and 30 seconds")
    if not scenes:
        return []
    start, end = scenes[0][0], scenes[-1][1]
    origin = start.get_seconds()
    length = end.get_seconds() - origin
    total = max(1, whole_second(length))
    n = math.ceil(total / limit)
    cuts = [s for s, _ in scenes[1:]]
    points = [start]
    elapsed = 0
    for remaining in range(n - 1, 0, -1):
        # Leave at least one second and at most one limit per remaining request.
        low = max(elapsed + 1, total - remaining * limit)
        high = min(elapsed + limit, total - remaining)
        target = elapsed + (total - elapsed) / (remaining + 1)
        available = (p for p in cuts if low <= whole_second(p.get_seconds() - origin) <= high)
        boundary = min(available, key=lambda p: abs(p.get_seconds() - origin - target), default=None)
        if boundary is None:
            target = min(high, max(low, whole_second(target)))
            boundary = start + round(target * start.get_framerate())
        points.append(boundary)
        elapsed = whole_second(boundary.get_seconds() - origin)
    return list(zip(points, [*points[1:], end], strict=True))


def natural_production_ranges(scenes, limit):
    """Choose a frame-contiguous path, preferring real edits, then fewer, more even requests."""
    if not 1 <= limit <= 30:
        raise ValueError("Generation shot limit must be between 1 and 30 seconds")
    if not scenes:
        return []
    start, end = scenes[0][0], scenes[-1][1]
    origin = start.get_seconds()
    if whole_second(end.get_seconds() - origin) <= limit:
        return [(start, end)]

    points = {point.get_frames(): point for point in [start, *(b for _, b in scenes)]}
    natural = set(points)
    # Only an uninterrupted take longer than the budget needs artificial cut candidates.
    for a, b in scenes:
        first = whole_second(a.get_seconds() - origin)
        last = whole_second(b.get_seconds() - origin)
        if last - first > limit:
            for second in range(first + 1, last):
                point = start + round(second * start.get_framerate())
                if a < point < b:
                    points.setdefault(point.get_frames(), point)

    ordered = [points[frame] for frame in sorted(points)]
    seconds = [whole_second(p.get_seconds() - origin) for p in ordered]
    costs = [None] * len(ordered)
    parents = [-1] * len(ordered)
    costs[0] = (0, 0, 0)
    for i in range(1, len(ordered)):
        artificial = ordered[i].get_frames() not in natural
        for j in range(i - 1, -1, -1):
            duration = seconds[i] - seconds[j]
            if duration > limit:
                break
            if duration == 0 or costs[j] is None:
                continue
            forced, count, deviation = costs[j]
            score = (forced + artificial, count + 1, deviation + (limit - duration) ** 2)
            if costs[i] is None or score < costs[i]:
                costs[i], parents[i] = score, j

    ranges = []
    i = len(ordered) - 1
    while i > 0:
        j = parents[i]
        if j < 0:
            raise ValueError("The source frame spacing exceeds the shot duration limit")
        ranges.append((ordered[j], ordered[i]))
        i = j
    return ranges[::-1]
