"""Check transcribed dialogue at physical cuts. Never infer an omission from text similarity alone."""
import asyncio
import re
import unicodedata
from copy import deepcopy
from hashlib import sha256


def speech_text(value):
    # The prefix may itself contain timestamps, a speaker name, tone, and punctuation.
    match = re.match(r'^([^：:\n]{1,48}[：:]\s*[^：:\n]{1,160}[：:]\s*)(.+)$', value)
    return (match[1], match[2]) if match else ('', value)


def normalized_words(value):
    return ''.join(c.casefold() for c in unicodedata.normalize('NFKC', value) if c.isalnum())


def repeated_lines(previous, current):
    for field in ('dialogue', 'narration'):
        left = previous.get(field) or []
        right = current.get(field) or []
        if not left or not right:
            continue
        _, last = speech_text(left[-1])
        _, first = speech_text(right[0])
        text = normalized_words(last)
        if len(text) >= 4 and text == normalized_words(first):
            yield field, last, first


def replace_quotation(text, original, replacement):
    for opening, closing in (("“", "”"), ("「", "」"), ("‘", "’"), ('"', '"')):
        new = f"{opening}{replacement}{closing}" if replacement else ""
        text = text.replace(f"{opening}{original}{closing}", new)
    return text


def apply_speech_evidence(previous, current, field, left, right):
    """Keep intentional repetitions; apply a partition only if it accounts for the entire original line."""
    old_left = previous[field][-1]
    old_right = current[field][0]
    left_prefix, last = speech_text(old_left)
    right_prefix, first = speech_text(old_right)
    original = normalized_words(last)
    a, b = normalized_words(left.words), normalized_words(right.words)
    if not left.certain or not right.certain:
        return 'unresolved'
    if original == a == b:
        return 'source_repetition'
    if original != normalized_words(first) or a + b != original:
        return 'unresolved'
    for shot, pos, prefix, old, words in ((previous,-1,left_prefix,last,left.words),(current,0,right_prefix,first,right.words)):
        if words:
            shot[field][pos] = prefix + words
        else:
            shot[field].pop(pos)
        if words == old:
            continue
        # Only replace an exact quotation, never remove actions, cut a shot, or edit other dialogue.
        for key in ('description','visual_prose','sound_design'):
            if isinstance(shot.get(key), str):
                shot[key] = replace_quotation(shot[key], old, words)
        if 'actions' in shot:
            shot['actions'] = [replace_quotation(line, old, words) for line in shot['actions']]
    return 'split_at_cut'


async def review_speech(shots, paths, gateway, saved, language):
    from prompts.remake import speech_boundary_instruction
    from schemas.remake import RemakeSpeechEvidence
    corrected = deepcopy(shots)
    boundaries = []
    requests = {}
    for i in range(1, len(shots)):
        for field, last, first in repeated_lines(shots[i-1], shots[i]):
            keys = []
            for position, line in ((i-1, last), (i, first)):
                key = f'{position+1}-{field}-' + sha256(line.encode()).hexdigest()[:16]
                requests[key] = (position, line)
                keys.append(key)
            boundaries.append((i, field, last, first, keys))

    async def observe(key):
        position, line = requests[key]
        stored = saved.get(f'model:structured:RemakeSpeechEvidence:{key}')
        if stored is None:
            stored = await gateway.analyze_one(index=position+1, path=paths[position], schema_name='shot_speech_evidence',
                prompt=speech_boundary_instruction(language), response_schema=RemakeSpeechEvidence.model_json_schema(),
                context={'segment':key,'shot_number':position+1,'line_to_locate':line}, include_segment_metadata=False)
        return RemakeSpeechEvidence.model_validate(stored)

    # Each observation hears one original clip. Independent checks share the same model admission window.
    values = await asyncio.gather(*(observe(key) for key in requests), return_exceptions=True)
    for value in values:
        if isinstance(value, BaseException):
            raise value
    evidence = dict(zip(requests, values, strict=True))
    decisions = []
    for i, field, last, first, keys in boundaries:
        previous, current = corrected[i-1], corrected[i]
        if (field, last, first) in repeated_lines(previous, current):
            decision = apply_speech_evidence(previous, current, field, *(evidence[key] for key in keys))
        else:
            decision = 'resolved_by_adjacent_cut'
        decisions.append({'previous':i, 'current':i+1, 'field':field, 'decision':decision})
    return corrected, decisions
