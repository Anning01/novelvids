"""Explain missing and stale memories without mutating their historical sources."""

from fastapi import HTTPException
from models.chapter import Chapter
from models.novel import Novel
from models.story_memory import StoryCommit, StorySnapshot
from services.creation_agent.plan_sources import fingerprint
from services.story_memory.sources import needs_opening_source, opening_source, snapshot_data
from services.story_memory.store import CANDIDATE_STATUSES


async def memory_status(novel_id):
    project = await Novel.get_or_none(id=novel_id)
    if project is None:
        raise HTTPException(404, '作品不存在')
    chapters = await Chapter.filter(novel_id=novel_id).order_by('number', 'id')
    opening = next((item for chapter in chapters if (item := opening_source(chapter))), None) if needs_opening_source(project) else None
    # Load each table once; status must not rescan every prefix for every chapter.
    latest, attempts = {}, {}
    for commit in await StoryCommit.filter(novel_id=novel_id).order_by('-id').only(
            'id', 'chapter_id', 'parent_id', 'source_hash', 'status'):
        attempts.setdefault(commit.chapter_id, commit)
        if commit.status == 'accepted':
            latest.setdefault(commit.chapter_id, commit)
    snapshots = {row['commit_id']: row['data'] for row in await StorySnapshot.filter(
        novel_id=novel_id, commit_id__in=[commit.id for commit in latest.values()]).values('commit_id', 'data')}
    result = []
    parent_id, blocked_by = None, None
    for chapter in [None, *chapters]:
        chapter_id = chapter.id if chapter else None
        commit = latest.get(chapter_id)
        attempt = attempts.get(chapter_id)
        candidate = attempt if attempt and attempt.status in CANDIDATE_STATUSES else None
        snapshot = snapshots.get(commit.id) if commit else None
        invalidation = snapshot.get('invalidation') if snapshot else None
        reason = None
        if commit is None:
            reason = '尚未建立正式记忆'
        elif fingerprint(snapshot_data(project, chapter, opening=opening if chapter is None else None)) != commit.source_hash:
            reason = '剧本或项目设定已变化'
        elif invalidation:
            reason = '来源或前情变化后尚未重新确认'
        elif snapshot is None:
            reason = '正式记忆快照缺失'
        elif blocked_by:
            reason = blocked_by
        elif commit.parent_id != parent_id:
            reason = '前置故事提交已变化'
        result.append({'chapter_id': chapter_id, 'number': chapter.number if chapter else None,
            'commit_id': commit.id if commit else None,
            'candidate_id': candidate.id if candidate else None, 'candidate_status': 'ready' if candidate else None,
            'state': 'missing' if commit is None else 'stale' if reason else 'current',
            'reason': reason, 'can_analyze': blocked_by is None, 'blocked_by': blocked_by,
            'invalidation': invalidation})
        if reason and blocked_by is None:
            blocked_by = f'第 {chapter.number} 章记忆需要重新确认' if chapter else '全局故事底稿需要重新确认'
        parent_id = commit.id if commit else None
    return {'baseline': result[0], 'chapters': result[1:]}
