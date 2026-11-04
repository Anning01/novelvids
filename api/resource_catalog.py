"""Unified catalog, preserving legacy video and voice endpoints."""
import mimetypes
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from auth.deps import AuthContext, get_auth_context, require_roles
from api.resource_library import library_team
from models.resource_library import VideoResource
from schemas.resource_library import CatalogKind, MediaKind, CatalogUpload, CatalogMove, CatalogPublish, CatalogApply, ResourceRename
from services.resource_catalog import resource_catalog, parse_key
from services.resource_storage import library_media_storage
from controllers.resource_library import resource_library_controller as library
from services.oss import oss
from utils.response_format import ResponseSchema
from utils.messages import localized_message as msg

router=APIRouter()
_EDITOR=Depends(require_roles('admin','creator'))


@router.get('/capabilities')
async def capabilities(team:int=Depends(library_team)):
    from config import settings
    from services.audio_references import MAX_AUDIO_BYTES, SUPPORTED_AUDIO_EXTENSIONS, MIN_AUDIO_DURATION, MAX_AUDIO_DURATION
    return ResponseSchema(data={'kinds':{kind:{'formats':formats,'max_size_mb':settings.RESOURCE_LIBRARY_MAX_SIZE_MB} for kind,formats in library_media_storage.formats_by_kind.items()},
        'voice':{'formats':[ext.lstrip('.') for ext in sorted(SUPPORTED_AUDIO_EXTENSIONS)],'max_size_mb':MAX_AUDIO_BYTES//(1024*1024),'min_duration':MIN_AUDIO_DURATION,'max_duration':MAX_AUDIO_DURATION},'folder_depth':2})


@router.get('/projects')
async def projects(team:int=Depends(library_team),page:int=Query(1,ge=1)):
    from models.novel import Novel
    query=Novel.filter(team_id=team or None)
    total=await query.count()
    rows=await query.order_by('-updated_at').offset((page-1)*100).limit(100).values('id','name','created_at','updated_at')
    return ResponseSchema(data={'items':rows,'pagination':{'total':total,'page':page,'page_size':100,'pages':(total+99)//100}})


@router.get('/project-assets')
async def shared_assets(asset_type:int=Query(...,ge=1,le=3),search:str=Query('',max_length=255),page:int=Query(1,ge=1),page_size:int=Query(24,ge=1,le=100),team:int=Depends(library_team)):
    from models.resource_library import ResourcePlacement
    from models.asset import Asset
    from schemas.asset import AssetWithVariantsOut
    ids=await ResourcePlacement.filter(team_id=team,catalog='asset').values_list('source_id',flat=True)
    query=Asset.filter(id__in=ids,asset_type=asset_type,novel__team_id=team or None)
    if search.strip():
        query=query.filter(canonical_name__icontains=search.strip())
    total=await query.count()
    rows=await query.order_by('canonical_name').offset((page-1)*page_size).limit(page_size).prefetch_related('variants')
    return ResponseSchema(data={'items':[AssetWithVariantsOut.model_validate(row).model_dump(mode='json') for row in rows],
        'pagination':{'total':total,'page':page,'page_size':page_size,'pages':(total+page_size-1)//page_size}})


@router.get('')
async def catalog(kind:CatalogKind='all', folder_id:int|None=Query(None,ge=0), search:str=Query('',max_length=255), origin:str=Query('all',pattern='^(all|team|system|personal)$'),
    page:int=Query(1,ge=1,le=200),page_size:int=Query(24,ge=1,le=100),sort:str=Query('recent',pattern='^(recent|name)$'),
    gender:str=Query('',max_length=32),country:str=Query('',max_length=64),age:str=Query('',max_length=16),occupation:str=Query('',max_length=100),
    team:int=Depends(library_team),ctx:AuthContext=Depends(get_auth_context)):
    return ResponseSchema(data=await resource_catalog.list(team,ctx,kind=kind,folder_id=folder_id,search=search.strip(),origin=origin,page=page,page_size=page_size,sort=sort,gender=gender,country=country,age=age,occupation=occupation))


@router.post('/upload-policy')
async def upload_policy(payload:CatalogUpload,team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    library_media_storage.check_kind(payload.filename,payload.kind)
    if not oss.enabled:
        return ResponseSchema(data={'direct':False})
    row=await library.reserve(team,ctx.user.id if ctx.user else None,payload.filename,payload.folder_id,kind=payload.kind)
    try:
        policy=oss.sign_form_upload(row.storage_ref,mimetypes.guess_type(payload.filename)[0] or 'application/octet-stream',library_media_storage.max_bytes)
    except Exception:
        await library.cancel_upload(team,row.id);raise
    return ResponseSchema(data={'direct':True,'resource_id':row.id,'upload_url':policy['url'],'fields':policy['fields']})


@router.post('/upload')
async def upload(kind:MediaKind=Form(...),folder_id:int=Form(0,ge=0),file:UploadFile=File(...),team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    row=await library.reserve(team,ctx.user.id if ctx.user else None,file.filename or '',folder_id,kind=kind)
    try:
        await library_media_storage.upload(row.storage_ref,file)
        row=await library.finalize(team,row.id)
    except Exception:
        await VideoResource.filter(id=row.id,state='uploading').update(state='delete_failed')
        await library.delete_resources(team,[row.id]);raise
    return ResponseSchema(data=await resource_catalog.describe(team,'media',row))


@router.post('/resources/{resource_id}/finalize')
async def finalize(resource_id:int,team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    row=await library.finalize(team,resource_id)
    return ResponseSchema(data=await resource_catalog.describe(team,'media',row))


@router.post('/voices/upload')
async def upload_voice(nickname:str=Form(...,min_length=1,max_length=100),gender:str=Form('未设置',max_length=32),folder_id:int=Form(0,ge=0),file:UploadFile=File(...),team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    from services.audio_references import save_uploaded_audio_reference
    from models.resource_library import ResourcePlacement
    await library.folder(team,folder_id)
    row=await save_uploaded_audio_reference(file,nickname=nickname,gender=gender,team_id=team or None,created_by=ctx.user.id if ctx.user else None)
    await ResourcePlacement.get_or_create(team_id=team,catalog='voice',source_id=row.id,defaults={'folder_id':folder_id})
    return ResponseSchema(data=await resource_catalog.describe(team,'voice',row))


@router.post('/move')
async def move(payload:CatalogMove,team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    await resource_catalog.move(team,ctx,payload.keys,payload.folder_id)
    return ResponseSchema(data=None)


@router.post('/publish')
async def publish(payload:CatalogPublish,team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    if payload.catalog=='asset':
        result=await resource_catalog.publish_asset(team,ctx,payload.source_id,payload.folder_id)
    else:
        from services.catalog_publication import publish_editor_resource
        result=await publish_editor_resource(team,ctx,payload)
    return ResponseSchema(data=result)


@router.get('/{key}')
async def get(key:str,team:int=Depends(library_team),ctx:AuthContext=Depends(get_auth_context)):
    catalog,row=await resource_catalog.get(team,ctx,key)
    return ResponseSchema(data=await resource_catalog.describe(team,catalog,row))


@router.post('/{key}/apply')
async def apply(key:str,payload:CatalogApply,team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    from services.catalog_applications import apply_catalog_resource
    return ResponseSchema(data=await apply_catalog_resource(team,ctx,key,payload))


@router.patch('/{key}')
async def rename(key:str,payload:ResourceRename,team:int=Depends(library_team),ctx:AuthContext=_EDITOR):
    return ResponseSchema(data=await resource_catalog.rename(team,ctx,key,payload.name))
