"""Editor endpoints: typed data only, scoped by existing chapter/project checks."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from auth.deps import AuthContext, get_auth_context
from models.chapter_export import ChapterExport
from schemas.video_edit import EditSave, EditExportIn, EditLibraryIn, EditSource, SubtitleRecognizeIn, SubtitleSplitIn
from services.video_editor.drafts import chapter_scope, read_draft, save_draft
from services.video_editor.assets import editor_storage, FORMATS
from services.video_editor.sources import EditSources, public_media
from services.video_editor.exports import submit_export, describe_export
from utils.response_format import ResponseSchema
from utils.subtitle_fonts import SUBTITLE_FONTS, subtitle_font_options
from utils.messages import localized_message as msg

router = APIRouter()


@router.get('/capabilities')
async def capabilities(ctx: AuthContext = Depends(get_auth_context)):
    from config import settings
    from services.video_editor.subtitles import subtitle_styles
    return ResponseSchema(data={'subtitle_styles': subtitle_styles(),'formats': FORMATS, 'max_size_mb': settings.RESOURCE_LIBRARY_MAX_SIZE_MB,
        'max_duration': settings.VIDEO_EDITOR_MAX_DURATION_SECONDS, 'max_overlays': settings.VIDEO_EDITOR_MAX_OVERLAYS,
        'max_audio_tracks': settings.VIDEO_EDITOR_MAX_AUDIO_TRACKS, 'fps': [24, 25, 30, 60],
        'max_source_mb': settings.VIDEO_EDITOR_MAX_SOURCE_MB,
        'resolutions': [480, 720, 1080, 1440, 2160], 'fonts': subtitle_font_options()})


@router.get('/subtitle-fonts/{font_id}', response_class=FileResponse)
async def subtitle_font_file(font_id: str, ctx: AuthContext = Depends(get_auth_context)):
    from services.video_editor.fonts import cached_subtitle_font
    if font_id not in SUBTITLE_FONTS:
        raise HTTPException(404, msg('字幕字体不存在'))
    try:
        path = await cached_subtitle_font(font_id)
    except ValueError as error:
        raise HTTPException(502, str(error)) from None
    return FileResponse(path, media_type=f'font/{path.suffix[1:]}', headers={'Cache-Control': 'private, max-age=86400'})


@router.get('/chapters/{chapter_id}')
async def draft(chapter_id: int, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await read_draft(chapter_id, ctx))


@router.put('/chapters/{chapter_id}')
async def save(chapter_id: int, payload: EditSave, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await save_draft(chapter_id, payload, ctx))


@router.post('/chapters/{chapter_id}/assets')
async def upload(chapter_id: int, kind: str, file: UploadFile = File(...), ctx: AuthContext = Depends(get_auth_context)):
    chapter = await chapter_scope(chapter_id, ctx, write=True)
    return ResponseSchema(data=await editor_storage.import_file(chapter, file, kind, ctx))


@router.post('/chapters/{chapter_id}/library')
async def library(chapter_id: int, payload: EditLibraryIn, ctx: AuthContext = Depends(get_auth_context)):
    chapter = await chapter_scope(chapter_id, ctx, write=True)
    item = await EditSources(chapter.novel_id, chapter.id).resolve(EditSource(kind='library', id=payload.resource_id))
    return ResponseSchema(data=public_media(item))


@router.post('/chapters/{chapter_id}/exports')
async def export(chapter_id: int, payload: EditExportIn, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await describe_export(await submit_export(chapter_id, payload.revision, ctx)))


@router.get('/chapters/{chapter_id}/exports')
async def history(chapter_id: int, ctx: AuthContext = Depends(get_auth_context)):
    await chapter_scope(chapter_id, ctx)
    rows, offset = [], 0
    while len(rows) < 20:
        page = await ChapterExport.filter(chapter_id=chapter_id).order_by('-id').offset(offset).limit(100)
        rows.extend(row for row in page if row.recipe.get('kind') == 'editor_render')
        if len(page) < 100:
            break
        offset += 100
    rows = rows[:20]
    return ResponseSchema(data=[await describe_export(row) for row in rows])


@router.post('/chapters/{chapter_id}/subtitles/recognize')
async def recognize_subtitles(
    chapter_id: int,
    payload: SubtitleRecognizeIn | None = None,
    ctx: AuthContext = Depends(get_auth_context),
):
    from services.video_editor.recognition import recognize_and_apply_subtitles
    document = payload.document if payload else None
    result = await recognize_and_apply_subtitles(chapter_id, ctx, client_document=document)
    return ResponseSchema(data=result)


@router.post('/chapters/{chapter_id}/subtitles/split')
async def split_subtitles(chapter_id: int, payload: SubtitleSplitIn, ctx: AuthContext = Depends(get_auth_context)):
    from services.video_editor.recognition import split_document_subtitles
    return ResponseSchema(data=await split_document_subtitles(chapter_id, ctx, payload.document, payload.ids))
