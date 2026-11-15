"""Read-only migration portal for retired studio projects, separate from Cat API."""
from contextlib import asynccontextmanager
import os
import re
from urllib.parse import urlsplit, urlunsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse
import httpx
from pydantic import BaseModel, Field
from tortoise import Tortoise
from tortoise.expressions import Q

from config import settings
from exceptions.handlers import http_exception_handler, validation_exception_handler
from auth.models import Team, TeamMember
from models.novel import Novel
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from services.project_transfer.snapshot import project_snapshot
from services.project_transfer.downloads import export_plan
from services.project_transfer.archive import ArchiveError
from services.oss import resolve_media_url
from utils.response_format import ResponseSchema

PREFIX = '/api/legacy-works'


class Principal(BaseModel):
    id: int = Field(gt=0)
    is_super_admin: bool = False


async def current_principal(request: Request) -> Principal:
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer ') or len(authorization) > 512:
        raise HTTPException(401, '请先登录 Cat API')
    origin = os.environ.get('CAT_API_ORIGIN', 'http://127.0.0.1:9000').rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(origin+'/api/auth/me', headers={'Authorization':authorization})
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, '登录服务暂不可用，请重试') from None
    if body.get('code') != 0:
        raise HTTPException(401, '登录已失效，请重新登录')
    return Principal.model_validate(body['data']['user'])


async def visible_projects(user: Principal):
    if user.is_super_admin:
        return Novel.all()
    memberships = await TeamMember.filter(user_id=user.id,status=1,team__status=1).values_list('team_id',flat=True)
    owned = await Team.filter(owner_user_id=user.id,status=1).values_list('id',flat=True)
    return Novel.filter(team_id__in=set(memberships)|set(owned))


async def authorized_project(project_id: int, user: Principal):
    project = await (await visible_projects(user)).filter(id=project_id).first()
    if project is None:
        raise HTTPException(404, '作品不存在或无权访问')
    return project


@asynccontextmanager
async def lifespan(_app):
    # A migration copy can evolve for archive compatibility; never initialize against the live database.
    name=os.environ.get('ARCHIVE_DATABASE_NAME','')
    parts=urlsplit(settings.DATABASE_URL)
    if parts.scheme not in {'postgres','postgresql'} or not re.fullmatch('[a-z][a-z0-9_]*',name) or parts.path=='/'+name:
        raise RuntimeError('A separate archive database is required')
    settings.DATABASE_URL=urlunsplit((parts.scheme,parts.netloc,'/'+name,parts.query,parts.fragment))
    settings.DEPLOYMENT_ROLE='platform'
    from main import _initialize_database_schema
    await _initialize_database_schema()
    try:
        yield
    finally:
        await Tortoise.close_connections()


app=FastAPI(title='Historical project migration',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
@app.middleware('http')
async def private_responses(request,call_next):
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


app.add_exception_handler(HTTPException,http_exception_handler)
app.add_exception_handler(RequestValidationError,validation_exception_handler)


@app.get(PREFIX+'/health')
async def health():
    await Tortoise.get_connection('default').execute_query('SELECT 1')
    return {'status':'ok','read_only':True,'automatic_deletion':False}


@app.get(PREFIX+'/projects')
async def projects(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),search:str=Query('',max_length=100),user=Depends(current_principal)):
    query=await visible_projects(user)
    if search.strip():query=query.filter(name__icontains=search.strip())
    total=await query.count()
    records=await query.order_by('-updated_at','-id').offset((page-1)*page_size).limit(page_size)
    items=[]
    for project in records:
        items.append({'id':project.id,'name':project.name,'description':project.description,
            'chapters':await Chapter.filter(novel_id=project.id).count(),
            'cover':resolve_media_url(project.cover),'updated_at':project.updated_at})
    return ResponseSchema(data={'items':items,'pagination':{'total':total,'page':page,'page_size':page_size,
        'pages':(total+page_size-1)//page_size},'automatic_deletion':False})


async def transfer(project_id,user,layouts=None):
    project=await authorized_project(project_id,user)
    try:
        plan=export_plan(await project_snapshot(project.id,browser_layouts=layouts),project.team_id)
    except ArchiveError as error:
        raise HTTPException(422,str(error)) from None
    # Thumbnails viewed before migration can be cached for a year without CORS headers.
    # Give unsigned storage downloads a separate, stable browser cache entry.
    storage_origin = urlsplit(resolve_media_url('uploads/0/migration.webp') or '').netloc
    for file in plan['files']:
        if file['authenticated']:
            file['url']=file['url'].replace('/api/video/exports/',PREFIX+'/exports/',1)
        else:
            url = urlsplit(file['url'])
            if storage_origin and url.scheme == 'https' and url.netloc == storage_origin and not url.query:
                file['url'] = url._replace(query='cat-migration=1').geturl()
    return ResponseSchema(data=plan)


@app.get(PREFIX+'/projects/{project_id}/snapshot')
async def raw_snapshot(project_id:int,user=Depends(current_principal)):
    await authorized_project(project_id,user)
    return ResponseSchema(data=await project_snapshot(project_id))


@app.get(PREFIX+'/projects/{project_id}/transfer')
async def get_transfer(project_id:int,user=Depends(current_principal)):
    return await transfer(project_id,user)


@app.post(PREFIX+'/projects/{project_id}/transfer')
async def transfer_with_browser_canvas(project_id:int,layouts:dict[str,dict],user=Depends(current_principal)):
    # Browser canvas data is validated and included in the response; it is never saved online.
    return await transfer(project_id,user,layouts)


@app.get(PREFIX+'/exports/{export_id}/download')
async def export_file(export_id:int,source:bool=False,user=Depends(current_principal)):
    export=await ChapterExport.get_or_none(id=export_id,collection_complete=True)
    if export is None:raise HTTPException(404,'成片不存在')
    await authorized_project(export.novel_id,user)
    reference=export.source_media_ref if source else export.media_ref
    if not reference:raise HTTPException(404,'成片文件尚未就绪')
    if reference.startswith('/media/'):
        from services.video_enhancement.media import export_media
        path=export_media.local_path(reference)
        if not path.is_file():raise HTTPException(404,'成片文件不存在')
        return FileResponse(path,media_type='video/mp4',filename=f'chapter-{export.chapter_id}-export-{export.id}.mp4')
    return RedirectResponse(resolve_media_url(reference),status_code=307)
