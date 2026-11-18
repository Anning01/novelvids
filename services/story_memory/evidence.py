"""Anchor model quotations to the immutable source; never infer missing evidence."""

import re
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
            if start >= 0:
                if text.find(evidence.quote, start + 1) < 0:
                    item.update(start=start, end=start + len(evidence.quote))
                continue
            # Model output may collapse blank lines. Restore the original only at a unique match.
            parts = re.split(r'[\r\n]+', evidence.quote)
            if len(parts) > 1 and parts[0] and parts[-1]:
                pattern = re.compile(r'[\r\n]+'.join(map(re.escape, parts)))
                match = pattern.search(text)
                if match and pattern.search(text, match.start() + 1) is None:
                    item.update(start=match.start(), end=match.end(), quote=match.group())
    return candidate
