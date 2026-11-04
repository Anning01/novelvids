"""Optimistic revision writes over the existing project transaction boundary."""
from fastapi import HTTPException
from auth.deps import ensure_novel_access, require_roles
from models.chapter import Chapter
from models.novel import Novel
from models.video_edit import ChapterEditDraft
from schemas.video_edit import EditDocument
from services.creation_objects import project_write
from services.video_editor.sources import EditSources, public_media
from utils.messages import localized_message as msg


async def chapter_scope(chapter_id, ctx, *, write=False):
    chapter = await Chapter.get_or_none(id=chapter_id)
    if not chapter:
        raise HTTPException(404, msg('章节不存在'))
    await ensure_novel_access(chapter.novel_id, ctx)
    if write:
        await require_roles('admin', 'creator')(ctx)
        from services.video_enhancement.sources import require_generation_scope
        await require_generation_scope(chapter.novel_id, ctx.team_id)
    return chapter


async def initial_document(chapter, catalog):
    novel = await Novel.get(id=chapter.novel_id).only('id', 'description', 'aspect_ratio', 'resolution')
    legacy = (novel.description or '').split(' · ')
    ratios = {'9:16', '16:9', '1:1', '4:3', '3:4', '21:9'}
    ratio = novel.aspect_ratio if novel.aspect_ratio in ratios else next((p for p in legacy if p in ratios), '16:9')
    w, h = (int(n) for n in ratio.split(':'))
    from services.video_enhancement.contract import resolution_short_side
    side = resolution_short_side(novel.resolution or '') or 720
    side = min(2160, max(64, side))
    height = side if w >= h else round(side * h / w / 2) * 2
    width = round(height * w / h / 2) * 2
    if max(width, height) > 3840:
        scale = 3840 / max(width, height)
        width, height = round(width * scale / 2) * 2, round(height * scale / 2) * 2
    clips, start = [], 0
    for item in catalog:
        if 'sequence' not in item:
            continue
        duration = max(.05, float(item.get('duration') or 4))
        clips.append({'id': f"scene-{item['scene_id']}", 'type': 'video', 'name': item['name'],
                      'start': round(start, 6), 'duration': duration, 'source': item['source']})
        start += duration
    return EditDocument(width=width, height=height, clips=clips)


async def read_draft(chapter_id, ctx):
    chapter = await chapter_scope(chapter_id, ctx)
    resolver = EditSources(chapter.novel_id, chapter.id)
    catalog = await resolver.catalog()
    draft = await ChapterEditDraft.get_or_none(chapter_id=chapter.id)
    document = EditDocument.model_validate(draft.document) if draft else await initial_document(chapter, catalog)
    known = {item['key'] for item in catalog}
    for clip in document.clips:
        source = getattr(clip, 'source', None)
        if source and f'{source.kind}:{source.id}' not in known:
            try:
                catalog.append(await resolver.resolve(source))
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                catalog.append({'key': f'{source.kind}:{source.id}', 'source': source.model_dump(),
                                'kind': clip.type, 'name': clip.name, 'missing': True})
            known.add(f'{source.kind}:{source.id}')
    return {'revision': draft.revision if draft else 0, 'document': document.model_dump(mode='json'),
            'media': [public_media(item) for item in catalog], 'updated_at': draft.updated_at.isoformat() if draft else None}


async def save_draft(chapter_id, request, ctx):
    chapter = await chapter_scope(chapter_id, ctx, write=True)
    await EditSources(chapter.novel_id, chapter.id).validate(request.document)
    value = request.document.model_dump(mode='json')
    async with project_write(chapter.novel_id) as db:
        draft = await ChapterEditDraft.filter(chapter_id=chapter.id).using_db(db).select_for_update().first()
        if (draft.revision if draft else 0) != request.revision:
            raise HTTPException(409, msg('剪辑草稿已被其他页面修改，本地修改已保留，请重新核对'))
        if draft:
            if draft.document != value:
                draft.document, draft.revision = value, draft.revision + 1
                draft.updated_by = ctx.user.id if ctx.user else None
                await draft.save(using_db=db, update_fields=['document', 'revision', 'updated_by', 'updated_at'])
        else:
            draft = await ChapterEditDraft.create(chapter=chapter, document=value,
                updated_by=ctx.user.id if ctx.user else None, using_db=db)
    return {'revision': draft.revision, 'document': value, 'updated_at': draft.updated_at.isoformat()}
