"""Translate owned source events onto a shot-local generation timeline and carry the confirmed end state."""
import re

_RANGE = re.compile(r"^\s*\[?\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*[-–—~至]\s*(\d+(?:\.\d+)?)\s*(?:s|秒)?\s*\]?\s*[:：]?\s*", re.I)


def end_state_memory(shot, index):
    return {'previous_sequence': index, 'end_state': shot['transition'],
            'last_action': (shot.get('actions') or [''])[-1]}


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
            body = (f'从当前状态继续：{opening}；不重复起手。' if language == 'zh' else
                    f'Continue from the current state: {opening}. Do not restart the movement.')
        elif a < start and language is not None:
            body = ('仅延续跨切点动作：' if language == 'zh' else 'Continue the ongoing movement: ') + body
        local.append(f'{left:g}s-{right:g}s: {body}')
    return local


def finalize_generation_shots(shots, language):
    result = []
    previous = {}
    for raw in shots:
        observed = {}
        span = raw['source_interval']
        duration = span['output_seconds']
        shot = {**raw, 'duration': f'{duration}s', 'duration_seconds': duration,
                'generation_timeline': True, 'description': _RANGE.sub('',raw['description'],count=1)}
        for field in ('actions', 'dialogue', 'narration'):
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
                actions = _local_tracks(segment['actions'], span, language, previous.get('actions', set()),
                                        observed['actions'], segment['visual_prose'])
                rescaled.append({**segment, 'duration': length, 'actions': actions or [segment['visual_prose']]})
                elapsed += length
            shot['segments'] = rescaled
        shot['internal_cut_seconds'] = [
            round((t - span['start_seconds']) * duration / (span['end_seconds'] - span['start_seconds']), 3)
            for t in span.get('internal_cuts', []) if span['start_seconds'] < t < span['end_seconds']
        ]
        if result:
            prior = result[-1]
            shot['handoff'] = {**end_state_memory(prior, prior['shot_index']),
                               'source_end_seconds': prior['source_interval']['end_seconds']}
        result.append(shot)
        previous = observed
    return result
