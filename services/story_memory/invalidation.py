"""Invalidate derived snapshots in the same transaction as a source write."""

from datetime import datetime, timezone
from models.chapter import Chapter
from models.story_memory import StoryCommit, StoryFact, StoryMemoryProject, StorySnapshot, StorySubject


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
        settings = await StoryMemoryProject.get_or_none(novel_id=after.novel_id)
        split_source = bool(settings and settings.uses_split_source)
        if split_source or needs_opening_source(project):
            other = await first_opening_chapter(after.novel_id, exclude_id=after.id, prefer_original=split_source)

            def sample(chapter):
                source = opening_source(chapter, prefer_original=split_source)
                if source and (other is None or (chapter.number, chapter.id) < (other.number, other.id)):
                    return source
                return opening_source(other, prefer_original=split_source)

            if sample(before) != sample(after):
                start = None
    await invalidate(after.novel_id, chapter_id=after.id, from_number=start,
        reason='chapter_changed' if before else 'chapter_inserted')


async def chapter_removed(chapter):
    from models.novel import Novel
    from services.story_memory.sources import first_opening_chapter, needs_opening_source

    start = chapter.number
    settings = await StoryMemoryProject.get_or_none(novel_id=chapter.novel_id)
    split_source = bool(settings and settings.uses_split_source)
    if await StoryCommit.filter(novel_id=chapter.novel_id, chapter_id=None).exists():
        project = await Novel.get(id=chapter.novel_id)
        if split_source or needs_opening_source(project):
            opening = await first_opening_chapter(chapter.novel_id, prefer_original=split_source)
            if opening and opening.id == chapter.id:
                start = None

    # Deletion invalidates memory as a background dependency, with no user decision.
    if settings is None:
        later = await StoryCommit.filter(novel_id=chapter.novel_id, chapter__number__gt=chapter.number).exists()
        replacement_opening = start is None and await Chapter.filter(novel_id=chapter.novel_id).exclude(id=chapter.id).exists()
        if later or replacement_opening:
            await StoryMemoryProject.create(novel_id=chapter.novel_id, uses_split_source=False)

    await invalidate(chapter.novel_id, chapter_id=chapter.id, from_number=start, reason='chapter_deleted')
    commits = await StoryCommit.filter(novel_id=chapter.novel_id, chapter_id=chapter.id).values_list("id", flat=True)
    baselines = await StoryCommit.filter(novel_id=chapter.novel_id, chapter_id=None).values_list("id", "source_snapshot")
    commits.extend(identifier for identifier, source in baselines if (source.get("opening_chapter") or {}).get("id") == chapter.id)
    subjects = await StoryFact.filter(commit_id__in=commits).values_list("subject_id", flat=True)
    await StoryCommit.filter(id__in=commits).delete()
    used = await StoryFact.filter(subject_id__in=subjects).values_list("subject_id", flat=True)
    await StorySubject.filter(id__in=set(subjects).difference(used)).delete()
