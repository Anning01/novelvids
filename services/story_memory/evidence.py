"""Anchor model quotations to the immutable source; never infer missing evidence."""

from copy import deepcopy
from schemas.story_memory import StoryEvidence


def anchor_evidence(candidate, snapshot):
    candidate = deepcopy(candidate)
    for fact in candidate['facts']:
        for item in fact['evidence']:
            evidence = StoryEvidence.model_validate(item)
            section, key = evidence.source.split('.')
            text = (snapshot.get(section) or {}).get(key, '')
            if text[evidence.start:evidence.end] == evidence.quote and evidence.end <= len(text):
                continue
            start = text.find(evidence.quote)
            # Repeated quotations require correct explicit coordinates from the author/model.
            if start >= 0 and text.find(evidence.quote, start + 1) < 0:
                item.update(start=start, end=start + len(evidence.quote))
    return candidate
