"""Optimistic revision writes over the existing project transaction boundary."""
from fastapi import HTTPException
from auth.deps import ensure_novel_access, require_roles
from models.chapter import Chapter
from models.novel import Novel
from models.video_edit import ChapterEditDraft
from models.scene import Scene
from schemas.video_edit import EditDocument, EditSource, VideoClip
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


def compact_video_track(document: EditDocument) -> bool:
    videos = sorted((clip for clip in document.clips if clip.type == 'video'), key=lambda clip: clip.start)
    frame = 0
    changed = False
    for clip in videos:
        start = frame / document.fps
        changed |= clip.start != start
        clip.start = start
        frame += round(clip.duration * document.fps)
    return changed


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
    fps = EditDocument.model_fields['fps'].default
    clips, frame = [], 0
    for item in catalog:
        if 'sequence' not in item:
            continue
        frames = max(1, round(float(item.get('duration') or 4) * fps))
        clips.append({'id': f"scene-{item['scene_id']}", 'type': 'video', 'name': item['name'],
                      'start': frame / fps, 'duration': frames / fps, 'source': item['source']})
        frame += frames
    return EditDocument(width=width, height=height, clips=clips)


async def read_draft(chapter_id, ctx):
    chapter = await chapter_scope(chapter_id, ctx)
    resolver = EditSources(chapter.novel_id, chapter.id)
    catalog = await resolver.catalog()
    draft = await ChapterEditDraft.get_or_none(chapter_id=chapter.id)
    document = EditDocument.model_validate(draft.document) if draft else await initial_document(chapter, catalog)
    original = document.model_dump(mode='json')
    if draft:
        await reconcile_scene_videos(document, catalog, chapter.id, draft.updated_at)
    compact_video_track(document)
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
            'needs_save': bool(draft and document.model_dump(mode='json') != original),
            'media': [public_media(item) for item in catalog], 'updated_at': draft.updated_at.isoformat() if draft else None}


async def reconcile_scene_videos(document, catalog, chapter_id, saved_at):
    """Fill pending scene slots without replacing pinned takes or rebuilding edits."""
    scene_media = {item['scene_id']: item for item in catalog if 'sequence' in item}
    for clip in document.clips:
        if clip.type != 'video' or clip.source.kind != 'missing':
            continue
        item = scene_media.get(clip.source.id)
        if not item or item.get('missing') or not item.get('url'):
            continue
        clip.source = EditSource.model_validate(item['source'])
        if clip.trim_in == 0 and clip.trim_out is None and clip.speed == 1:
            clip.duration = max(1, round(float(item['duration']) * document.fps)) / document.fps
    # A scene absent from an older saved edit may have been deliberately removed.
    # Only scenes created after that save are automatically appended.
    new_ids = set(await Scene.filter(chapter_id=chapter_id, created_at__gt=saved_at).values_list('id', flat=True))
    used_ids = {clip.id for clip in document.clips}
    used_sources = {(clip.source.kind, clip.source.id) for clip in document.clips if clip.type == 'video'}
    end = max((clip.start + clip.duration for clip in document.clips if clip.type == 'video'), default=0)
    for item in scene_media.values():
        identifier = f"scene-{item['scene_id']}"
        source = EditSource.model_validate(item['source'])
        if item['scene_id'] not in new_ids or identifier in used_ids or (source.kind, source.id) in used_sources:
            continue
        if len(document.clips) >= 500:
            break  # Keep excess material in the library; respect the editor's clip limit.
        duration = max(1, round(float(item.get('duration') or 4) * document.fps)) / document.fps
        document.clips.append(VideoClip(id=identifier, name=item['name'], type='video',
                                        start=end, duration=duration, source=source))
        end += duration


async def save_draft(chapter_id, request, ctx):
    chapter = await chapter_scope(chapter_id, ctx, write=True)
    compact_video_track(request.document)
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
