from time import time

BATCH_SECONDS = 300


def batch_deadline(sources, submitted_at=None):
    starts = [item['upload'].created_at.timestamp() for item in sources if item.get('upload')]
    starts.append(time() if submitted_at is None else submitted_at)
    return min(starts) + BATCH_SECONDS
