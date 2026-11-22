"""Translate owned source events onto a shot-local generation timeline and carry the confirmed end state."""
import re

_RANGE = re.compile(r"^\s*\[?\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*[-–—~至]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*\]?\s*[:：]?\s*", re.I)


def end_state_memory(shot, index):
    content = {field: shot[field] for field in (
        'source_prompt_text', 'description', 'visual_prose', 'actions', 'dialogue', 'narration',
        'spatial_relationships', 'transition',
    ) if field in shot}
    last = (shot.get('actions') or [''])[-1]
    memory = {'previous_sequence': index, 'end_state': shot.get('transition', ''), 'generated_content': content}
    if isinstance(last, dict) and 'text' not in last:
        return {**memory, 'last_action': last['continuation'], 'action_key': last['key'], 'onset': last['onset']}
    return {**memory, 'last_action': last['text'] if isinstance(last, dict) else last}


def _local_tracks(lines, span, language, previous, observed, opening):
    start, end, duration = span['start_seconds'], span['end_seconds'], span['output_seconds']
    local = []
    for line in lines:
        match = _RANGE.match(line)
        if not match:
            local.append(line)
            continue
        a, b = map(float, match.groups())
        if b <= start or a >= end or a >= b:
            continue
        left = round((max(a, start) - start) * duration / (end - start), 3)
        right = round((min(b, end) - start) * duration / (end - start), 3)
        body = line[match.end():]
        event = (a, b, body)
        observed.add(event)
        if a < start and event in previous:
            if language is None:
                continue  # Same utterance and source occurrence already assigned to its onset.
            body = opening
        local.append(f'{left:g}s-{right:g}s: {body}')
    return local


def _local_second(source_second, span):
    start, end = span["start_seconds"], span["end_seconds"]
    bounded = min(end, max(start, source_second))
    return round((bounded - start) * span["output_seconds"] / (end - start), 3)


def _action_views(views, span, previous):
    """Only the view owning the physical onset can direct an actor to start the action."""
    lines = []
    current = {}
    unconfirmed_restarts = []
    for view in sorted(views, key=lambda item: item["start"]):
        left = max(view["start"], span["start_seconds"])
        right = min(view["end"], span["end_seconds"])
        if left >= right:
            continue
        key = " ".join(view["key"].casefold().split())
        onset = view["onset"]
        prior = current.get(key, previous.get(key))
        starts_here = left <= onset < right
        restart = view.get("restart")
        new_performance = prior is None or (restart is not None and prior < restart["at"] <= onset)
        if starts_here and prior is not None and onset > prior and not new_performance:
            unconfirmed_restarts.append({"key": view["key"], "source_seconds": onset})
        body = view["movement"] if starts_here and new_performance else view["continuation"]
        current[key] = onset if new_performance else prior
        lines.append(f"{_local_second(left, span):g}s-{_local_second(right, span):g}s: {body}")
    if not lines:
        lines = [v["movement"] for v in views]
    return lines, current, unconfirmed_restarts


def _display_cue(start, end, text, span):
    left, right = _local_second(start, span), _local_second(end, span)
    return f"{left:g}s-{right:g}s: {text}" if left < right else text


def _display_line(line, span):
    match = _RANGE.match(line)
    if not match:
        return line
    return _display_cue(float(match[1]), float(match[2]), line[match.end():], span)


def _local_sound(track, span):
    parts = [track["ambience"]]
    for cue in sorted(track["cues"], key=lambda item: item["start"]):
        left = _local_second(cue["start"], span)
        right = _local_second(cue["end"], span)
        if left < right:
            parts.append(f"{left:g}s-{right:g}s: {cue['sound']}")
    return " ".join(parts)


def finalize_generation_shots(shots, language):
    result = []
    previous = {}
    previous_views = {}
    for raw in shots:
        observed = {}
        span = raw['source_interval']
        duration = span['output_seconds']
        if 'source_prompt_text' in raw:
            result.append({**raw, 'duration': f'{duration}s', 'duration_seconds': duration})
            previous, previous_views = {}, {}
            continue
        shot = {**raw, 'duration': f'{duration}s', 'duration_seconds': duration,
                'generation_timeline': True, 'description': _RANGE.sub('',raw['description'],count=1)}
        tracks = ('actions', 'dialogue', 'narration')
        structured = bool(raw['actions'] and isinstance(raw['actions'][0], dict))
        authored_timeline = structured and 'text' in raw['actions'][0]
        if structured:
            if authored_timeline:
                shot['actions'] = [_display_cue(v['start'], v['end'], v['text'], span) for v in raw['actions']]
                audio = raw['sound_design']
                shot['sound_design'] = ' '.join([audio['ambience'], *[
                    _display_cue(c['start'], c['end'], c['sound'], span) for c in audio['cues']
                ]])
                for field in ('dialogue', 'narration'):
                    shot[field] = [_display_line(line, span) for line in raw.get(field, [])]
                tracks = ()
            else:
                shot['actions'], previous_views, suspects = _action_views(raw['actions'], span, previous_views)
                if suspects:
                    shot['unconfirmed_restarts'] = suspects
                shot['sound_design'] = _local_sound(raw['sound_design'], span)
                tracks = ('dialogue', 'narration')
        for field in tracks:
            observed[field] = set()
            shot[field] = _local_tracks(raw.get(field, []), span, language if field == 'actions' else None,
                                        previous.get(field, set()), observed[field], shot['visual_prose'])
        segments = raw.get('segments') or []
        if segments:
            total = sum(s['duration'] for s in segments)
            elapsed = 0
            rescaled = []
            for j, segment in enumerate(segments):
                length = duration - elapsed if j == len(segments)-1 else duration * segment['duration'] / total
                if authored_timeline:
                    actions = [_display_line(line, span) for line in segment['actions']]
                elif structured:
                    actions = [line for line in shot['actions']
                               if (timestamp := _RANGE.match(line)) and elapsed <= float(timestamp[1]) < elapsed + length]
                else:
                    actions = _local_tracks(segment['actions'], span, language, previous.get('actions', set()),
                                            observed['actions'], segment['visual_prose'])
                rescaled.append({**segment, 'duration': length, 'actions': actions or [segment['visual_prose']]})
                elapsed += length
            shot['segments'] = rescaled
        shot['internal_cut_seconds'] = [
            round((t - span['start_seconds']) * duration / (span['end_seconds'] - span['start_seconds']), 3)
            for t in span.get('internal_cuts', []) if span['start_seconds'] < t < span['end_seconds']
        ]
        result.append(shot)
        previous = observed
    return result
