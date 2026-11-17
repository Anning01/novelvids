"""Source snapshots and causal versions; no model calls or writes."""

from fastapi import HTTPException
from models.chapter import Chapter
from models.novel import Novel
from models.story_memory import StoryCommit, StorySnapshot
from services.creation_agent.plan_sources import fingerprint


def conflict(message):
    raise HTTPException(409, message)


async def source_snapshot(novel_id, chapter_id=None):
    project = await Novel.get_or_none(id=novel_id)
    if project is None:
        raise HTTPException(404, '作品不存在')
    source = {'project': {'name': project.name, 'setting': project.project_setting or '',
        'outline': project.story_outline or '', 'description': project.description or ''}, 'chapter': None}
    if chapter_id is not None:
        chapter = await Chapter.get_or_none(id=chapter_id, novel_id=novel_id)
        if chapter is None:
            raise HTTPException(404, '章节不属于当前作品')
        if not chapter.production_text.strip():
            raise HTTPException(422, '本章没有可分析的剧本或原文')
        source['chapter'] = {'id': chapter.id, 'number': chapter.number, 'name': chapter.name,
            'kind': 'screenplay' if chapter.screenplay else 'source', 'text': chapter.production_text}
    return source


async def latest_commit(novel_id, chapter_id):
    return await StoryCommit.filter(novel_id=novel_id, chapter_id=chapter_id, status='accepted').order_by('-id').first()


async def predecessor(novel_id, chapter_id):
    if chapter_id is None:
        return None
    chapter = await Chapter.get(id=chapter_id, novel_id=novel_id)
    parent = await latest_commit(novel_id, None)
    if parent is None:
        conflict('请先分析并确认全局故事底稿')
    if fingerprint(await source_snapshot(novel_id)) != parent.source_hash:
        conflict('全局故事底稿已过期，请重新分析并确认')
    for previous in await Chapter.filter(novel_id=novel_id, number__lt=chapter.number).order_by('number', 'id'):
        commit = await latest_commit(novel_id, previous.id)
        if (commit is None or commit.parent_id != parent.id
                or fingerprint(await source_snapshot(novel_id, previous.id)) != commit.source_hash):
            conflict(f'第 {previous.number} 章的正式记忆缺失或过期，请先完成前章提交')
        parent = commit
    return parent.id


async def verify_inputs(commit, *, check_target=True):
    if fingerprint(await source_snapshot(commit.novel_id, commit.chapter_id)) != commit.source_hash:
        conflict('剧本或项目设定已变化，请重新分析；原提交仍保留')
    if await predecessor(commit.novel_id, commit.chapter_id) != commit.parent_id:
        conflict('前置故事记忆已变化，请重新分析')
    if check_target:
        previous = await latest_commit(commit.novel_id, commit.chapter_id)
        if (previous.id if previous else None) != commit.replaces_id:
            conflict('本章已有新的正式提交，请重新分析')


async def parent_state(commit):
    if commit.parent_id is None:
        return {'fact_ids': [], 'summary': '', 'ending_state': '', 'unresolved': []}
    snapshot = await StorySnapshot.get(commit_id=commit.parent_id, novel_id=commit.novel_id)
    return snapshot.data
