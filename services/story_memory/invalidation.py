"""Invalidate derived snapshots in the same transaction as a source write."""

from datetime import datetime, timezone
from models.chapter import Chapter
from models.story_memory import StoryCommit, StorySnapshot


def chapter_source(chapter):
    return (chapter.number, chapter.name, bool(chapter.screenplay), chapter.production_text)


async def invalidate(novel_id, *, chapter_id=None, from_number=None, reason, exclude_commit_id=None):
    query = StorySnapshot.filter(novel_id=novel_id)
    candidates = StoryCommit.filter(novel_id=novel_id, status__in=['pending', 'draft', 'ready', 'needs_review'])
    if from_number is not None:
        ids = await Chapter.filter(novel_id=novel_id, number__gte=from_number).values_list('id', flat=True)
        query = query.filter(commit__chapter_id__in=ids)
        candidates = candidates.filter(chapter_id__in=ids)
    if exclude_commit_id is not None:
        query = query.exclude(commit_id=exclude_commit_id)
        candidates = candidates.exclude(id=exclude_commit_id)
    notice = {'reason': reason, 'chapter_id': chapter_id, 'from_number': from_number,
              'at': datetime.now(timezone.utc).isoformat()}
    await candidates.update(status='stale')
    for snapshot in await query:
        if snapshot.data.get('invalidation'):
            continue
        # Facts and original snapshots remain available for historical inspection.
        snapshot.data = {**snapshot.data, 'invalidation': notice}
        await snapshot.save(update_fields=['data', 'updated_at'])


async def chapter_changed(before, after):
    if before is not None and chapter_source(before) == chapter_source(after):
        return
    start = min(before.number, after.number) if before else after.number
    from models.novel import Novel
    from services.story_memory.sources import first_opening_chapter, needs_opening_source, opening_source
    if await StoryCommit.filter(novel_id=after.novel_id, chapter_id=None).exists():
        project = await Novel.get(id=after.novel_id)
        if needs_opening_source(project):
            other = await first_opening_chapter(after.novel_id, exclude_id=after.id)

            def sample(chapter):
                source = opening_source(chapter)
                if source and (other is None or (chapter.number, chapter.id) < (other.number, other.id)):
                    return source
                return opening_source(other)

            if sample(before) != sample(after):
                start = None
    await invalidate(after.novel_id, chapter_id=after.id, from_number=start,
        reason='chapter_changed' if before else 'chapter_inserted')
