"""SQL statement capture for tests that measure query counts.

The session-scoped ``sql_profiler`` fixture attaches its handler once when the
fixture is created, so a second ``async with`` block inside the same test would
silently capture nothing. This helper attaches per entry, is safe to reuse, and
keeps the measurement honest.
"""

import contextlib
import logging


class _Recorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.statements: list[str] = []

    def emit(self, record):
        self.statements.append(str(getattr(record, 'sql', None) or record.getMessage()))


@contextlib.asynccontextmanager
async def count_queries():
    logger = logging.getLogger('tortoise.db_client')
    original = logger.level
    recorder = _Recorder()
    logger.addHandler(recorder)
    logger.setLevel(logging.DEBUG)
    try:
        yield recorder.statements
    finally:
        logger.removeHandler(recorder)
        logger.setLevel(original)
