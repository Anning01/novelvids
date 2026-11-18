"""Source snapshots and causal versions; no model calls or writes."""

from fastapi import HTTPException
from tortoise.expressions import Q
from models.chapter import Chapter
from models.novel import Novel
from models.story_memory import StoryCommit, StorySnapshot
from services.creation_agent.plan_sources import fingerprint

OPENING_SAMPLE_LIMIT = 6000


def conflict(message):
    raise HTTPException(409, message)


def needs_opening_source(project):
    return not any((value or '').strip() for value in (project.project_setting, project.story_outline))


def opening_source(chapter):
    if chapter is None:
        return None
    script = chapter.screenplay or ''
    text = script if script.strip() else chapter.content
    if not text or not text.strip():
        return None
    return {'id': chapter.id, 'number': chapter.number, 'name': chapter.name,
        'kind': 'screenplay' if script.strip() else 'source', 'text': text[:OPENING_SAMPLE_LIMIT]}


async def first_opening_chapter(novel_id, exclude_id=None):
    chapters = Chapter.filter(Q(content__gt='') | Q(screenplay__gt=''), novel_id=novel_id).order_by('number', 'id')
    if exclude_id is not None:
        chapters = chapters.exclude(id=exclude_id)
    while (chapter := await chapters.first()) is not None:
        if opening_source(chapter):
            return chapter
        chapters = chapters.exclude(id=chapter.id)
    return None


def snapshot_data(project, chapter=None, *, opening=None):
    return {'project': {'name': project.name, 'setting': project.project_setting or '',
        'outline': project.story_outline or '', 'description': project.description or ''},
        'chapter': {'id': chapter.id, 'number': chapter.number, 'name': chapter.name,
            'kind': 'screenplay' if chapter.screenplay else 'source', 'text': chapter.production_text}
        if chapter else None, **({'opening_chapter': opening} if opening else {})}


async def source_snapshot(novel_id, chapter_id=None):
    project = await Novel.get_or_none(id=novel_id)
    if project is None:
        raise HTTPException(404, '作品不存在')
    chapter = None
    if chapter_id is not None:
        chapter = await Chapter.get_or_none(id=chapter_id, novel_id=novel_id)
        if chapter is None:
            raise HTTPException(404, '章节不属于当前作品')
        if not chapter.production_text.strip():
            raise HTTPException(422, '本章没有可分析的剧本或原文')
    opening = None
    if chapter is None and needs_opening_source(project):
        opening = opening_source(await first_opening_chapter(novel_id))
    return snapshot_data(project, chapter, opening=opening)


async def latest_commit(novel_id, chapter_id):
    return await StoryCommit.filter(novel_id=novel_id, chapter_id=chapter_id, status='accepted').order_by('-id').first()


async def predecessor(novel_id, chapter_id):
    if chapter_id is None:
        return None
    from services.story_memory.status import memory_status
    state = await memory_status(novel_id)
    if not any(item['chapter_id'] == chapter_id for item in state['chapters']):
        raise HTTPException(404, '章节不属于当前作品')
    parent = state['baseline']
    if parent['state'] != 'current':
        conflict('全局故事底稿缺失或已失效，请先分析并确认')
    for previous in state['chapters']:
        if previous['chapter_id'] == chapter_id:
            return parent['commit_id']
        if previous['state'] != 'current':
            conflict(f'第 {previous["number"]} 章的正式记忆缺失或过期，请先完成前章提交')
        parent = previous


async def verify_inputs(commit, *, check_target=True):
    if fingerprint(await source_snapshot(commit.novel_id, commit.chapter_id)) != commit.source_hash:
        conflict('剧本或项目设定已变化，请重新分析；原提交仍保留')
    if await predecessor(commit.novel_id, commit.chapter_id) != commit.parent_id:
        conflict('前置故事记忆已变化，请重新分析')
    if commit.status == 'stale':
        conflict('候选因来源或前情变化已失效，请重新分析')
    if commit.status == 'accepted':
        snapshot = await StorySnapshot.get_or_none(commit_id=commit.id)
        if snapshot and snapshot.data.get('invalidation'):
            conflict('本次正式记忆已失效，请重新分析并复核后续章节')
    if check_target:
        previous = await latest_commit(commit.novel_id, commit.chapter_id)
        if (previous.id if previous else None) != commit.replaces_id:
            conflict('本章已有新的正式提交，请重新分析')


async def parent_state(commit):
    if commit.parent_id is None:
        return {'fact_ids': [], 'summary': '', 'ending_state': '', 'unresolved': []}
    snapshot = await StorySnapshot.get(commit_id=commit.parent_id, novel_id=commit.novel_id)
    return snapshot.data
