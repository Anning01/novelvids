"""Scoped, explicit chapter export operations; no caller-supplied source URLs."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from api._production_request import production_request
from auth.deps import AuthContext, get_auth_context, require_chapter_access, require_video_access, require_roles
from models.chapter_export import ChapterExport
from schemas.video_export import ExportPrepareIn, ExportEnhanceIn, ExportTaskOut
from services.video_enhancement.contract import EnhancementOptions, EnhancementResolution, RESOLUTION_SHORT_SIDE
from controllers.chapter_export import chapter_exports
from services.ai_task_executor import ai_task_executor
from utils.response_format import ResponseSchema
from utils.messages import localized_message

router = APIRouter(dependencies=[Depends(production_request)])
EDITOR = Depends(require_roles('admin', 'creator'))


@router.post('', response_model=ResponseSchema[ExportTaskOut])
async def prepare_export(payload: ExportPrepareIn, background_tasks:BackgroundTasks,ctx: AuthContext=Depends(get_auth_context), _=EDITOR):
    try:
        export, task = await chapter_exports.prepare(payload.chapter_id, ctx, expected_version=payload.expected_source_version)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    background_tasks.add_task(ai_task_executor.run,task)
    return ResponseSchema(data=ExportTaskOut(export_id=export.id,task_id=str(task.id),status=task.status))


@router.get('')
async def list_exports(chapter_id: int, page: int=1, ctx: AuthContext=Depends(get_auth_context)):
    await require_chapter_access(chapter_id,ctx)
    page=max(1,page)
    rows=await ChapterExport.filter(chapter_id=chapter_id,source_video_id__isnull=True).order_by('-id').offset((page-1)*20).limit(20)
    from services.video_enhancement.sources import current_selection
    selection = await current_selection(chapter_id)
    return ResponseSchema(data=[await chapter_exports.describe(row,selection) for row in rows])


@router.get('/models')
async def export_models(ctx: AuthContext=Depends(get_auth_context)):
    return ResponseSchema(data=[{'id':row.id,'name':row.name,
        'input_short_side_max': EnhancementOptions.model_validate(row.processing_options or {}).input_short_side_max,
        'supported_resolutions':[{'value':value,'short_side':short} for value,short in RESOLUTION_SHORT_SIDE.items()],
        'resolutions':[{'value':value,'short_side':RESOLUTION_SHORT_SIDE[value]} for value in
            EnhancementOptions.model_validate(row.processing_options or {}).output_resolutions]}
        for row in await chapter_exports.configs(ctx)])


@router.get('/video/{video_id}')
async def list_video_exports(video_id:int,ctx:AuthContext=Depends(require_video_access)):
    rows = await ChapterExport.filter(source_video_id=video_id).order_by('-id').limit(20)
    return ResponseSchema(data=[await chapter_exports.describe(row) for row in rows])


@router.post('/video/{video_id}',response_model=ResponseSchema[ExportTaskOut])
async def prepare_video_export(video_id:int,background_tasks:BackgroundTasks,ctx:AuthContext=Depends(require_video_access),_=EDITOR):
    try:
        export,task = await chapter_exports.prepare_video(video_id,ctx)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    background_tasks.add_task(ai_task_executor.run,task)
    return ResponseSchema(data=ExportTaskOut(export_id=export.id,task_id=str(task.id),status=task.status))


@router.get('/{export_id}')
async def get_export(export_id:int,ctx:AuthContext=Depends(get_auth_context)):
    return ResponseSchema(data=await chapter_exports.describe(await chapter_exports.get(export_id,ctx)))


@router.get('/{export_id}/download')
async def download_export(export_id:int, source:bool=False,ctx:AuthContext=Depends(get_auth_context)):
    export = await chapter_exports.get(export_id,ctx)
    ref = export.source_media_ref if source else export.media_ref
    if not ref:
        raise HTTPException(404, localized_message('成片文件尚未就绪'))
    if ref.startswith('/media/'):
        from services.video_enhancement.media import export_media
        path = export_media.local_path(ref)
        if not path.is_file():
            raise HTTPException(404, localized_message('成片文件不存在或已移除'))
        resolution = (export.recipe or {}).get('resolution', 'source')
        return FileResponse(path, media_type='video/mp4', filename=f'chapter-{export.chapter_id}-export-{export.id}-{"source" if source else resolution}.mp4')
    from services.oss import resolve_media_url
    return RedirectResponse(resolve_media_url(ref), status_code=307)


@router.get('/{export_id}/quote')
async def quote_export(export_id:int,model_config_id:int,resolution:EnhancementResolution='1080p',ctx:AuthContext=Depends(get_auth_context),_=EDITOR):
    source=await chapter_exports.get(export_id,ctx)
    try:
        quote=await chapter_exports.quote(source,model_config_id,ctx,resolution)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    return ResponseSchema(data={key:quote[key] for key in ('amount','currency','source_sha256','quote_version','recipe','reused_export_id')})


@router.post('/{export_id}/enhance',response_model=ResponseSchema[ExportTaskOut])
async def enhance_export(export_id:int,payload:ExportEnhanceIn,background_tasks:BackgroundTasks,ctx:AuthContext=Depends(get_auth_context),_=EDITOR):
    try:
        export,task=await chapter_exports.enhance(export_id,payload,ctx)
    except ValueError as error:
        raise HTTPException(400,str(error)) from None
    background_tasks.add_task(ai_task_executor.run,task)
    return ResponseSchema(data=ExportTaskOut(export_id=export.id,task_id=str(task.id),status=task.status))
