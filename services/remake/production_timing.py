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
