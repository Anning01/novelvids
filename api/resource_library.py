"""团队共享视频库。请求中的目录/资源 ID 均重新校验团队归属。"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from auth.deps import AuthContext, auth_disabled, get_auth_context, require_roles
from controllers.config import ai_model_config_controller
from controllers.resource_library import (
    reference_dict, resource_dict, resource_for, resource_library_controller as library,
    validate_resource_model,
)
from models.resource_library import ResourceFolder, VideoResource
from services.resource_permissions import owner_scope, readable_scope, ensure_resource_write, is_public_resource
from schemas.resource_library import (
    FolderWrite, ResourceIds, ResourceImport, ResourceMove, ResourceRename,
    ResourceSelection, ResourceUpload,
)
from services.oss import oss
from services.resource_storage import resource_storage
from services.video.capabilities import capabilities_for
from utils.enums import AiTaskTypeEnum
from utils.response_format import ResponseSchema

router = APIRouter()
_EDITOR = Depends(require_roles("admin", "creator"))


async def library_team(request: Request, ctx: AuthContext = Depends(get_auth_context)) -> int | None:
    if auth_disabled():
        return 0
    if not ctx.is_super_admin:
        if not ctx.team_id:
            raise HTTPException(403, detail="请先选择团队")
        return ctx.team_id
    from auth.models import Team
    raw = request.headers.get("X-Team-Id", "")
    if not raw:
        return None
    if not raw.isdigit() or not await Team.filter(id=int(raw), status=1).exists():
        raise HTTPException(400, detail="目标团队不存在或已停用")
    return int(raw)


@router.get("/capabilities")
async def capabilities(team: int | None = Depends(library_team)):
    from config import settings
    return ResponseSchema(data={"formats": list(resource_storage.formats), "max_size_mb": settings.RESOURCE_LIBRARY_MAX_SIZE_MB, "folder_depth": 2})


@router.get("/folders")
async def folders(team: int | None = Depends(library_team), ctx: AuthContext = Depends(get_auth_context)):
    rows = await ResourceFolder.filter(readable_scope(team)).order_by("name")
    items = []
    for row in rows:
        public = await is_public_resource(row)
        editable = ctx.user is None or ctx.is_super_admin or (not public and ctx.membership and ctx.membership.role in {'admin', 'creator'})
        items.append({'id':row.id,'name':row.name,'parent_id':row.parent_id,'deleting':row.deleting,'editable':bool(editable),'team_id':row.team_id})
    return ResponseSchema(data=items)


@router.post("/folders")
async def create_folder(payload: FolderWrite, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    folder = await library.write_folder(team, ctx.user.id if ctx.user else None, payload)
    return ResponseSchema(data={"id": folder.id, **payload.model_dump(), "deleting": False})


@router.put("/folders/{folder_id}")
async def update_folder(folder_id: int, payload: FolderWrite, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    await ensure_resource_write(ctx, [await library.folder(None if ctx.is_super_admin else team, folder_id)])
    folder = await library.write_folder(None if ctx.is_super_admin else team, ctx.user.id if ctx.user else None, payload, folder_id)
    return ResponseSchema(data={"id": folder.id, **payload.model_dump(), "deleting": False})


@router.get("/resources")
async def resources(
    team: int | None = Depends(library_team), folder_id: int | None = Query(None, ge=0),
    search: str = Query("", max_length=255), page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    query = VideoResource.filter(readable_scope(team), kind='video', state__in=["ready", "delete_failed", "deleting"])
    if search.strip():
        query = query.filter(name__icontains=search.strip())
    elif folder_id is not None:
        await library.folder(team, folder_id, readable=True)
        query = query.filter(folder_id=folder_id)
    total = await query.count()
    items = await query.order_by("-id").offset((page - 1) * page_size).limit(page_size)
    return ResponseSchema(data={"items": [resource_dict(item) for item in items], "pagination": {
        "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size,
    }})


@router.post("/upload-policy")
async def upload_policy(payload: ResourceUpload, source: bool = False, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    if not oss.enabled:
        return ResponseSchema(data={"direct": False})
    resource = await library.reserve(team, ctx.user.id if ctx.user else None, payload.filename, payload.folder_id)
    if source:
        resource.is_source = True
        await resource.save(update_fields=["is_source"])
    mime = "video/quicktime" if payload.filename.lower().endswith(".mov") else "video/mp4"
    try:
        policy = oss.sign_form_upload(resource.storage_ref, mime, resource_storage.max_bytes)
    except Exception:
        await library.cancel_upload(team, resource.id)
        raise
    return ResponseSchema(data={"direct": True, "resource_id": resource.id, "upload_url": policy["url"], "fields": policy["fields"]})


@router.post("/upload")
async def upload(file: UploadFile = File(...), folder_id: int = Form(0, ge=0), source: bool = Form(False), team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    resource = await library.reserve(team, ctx.user.id if ctx.user else None, file.filename or "", folder_id)
    if source:
        resource.is_source = True
        await resource.save(update_fields=["is_source"])
    try:
        await resource_storage.upload(resource.storage_ref, file)
        resource = await library.finalize(team, resource.id)
    except Exception:
        await VideoResource.filter(id=resource.id, state="uploading").update(state="delete_failed")
        await library.delete_resources(team, [resource.id])
        raise
    return ResponseSchema(data=resource_dict(resource))


@router.post("/resources/{resource_id}/cancel-upload")
async def cancel_upload(resource_id: int, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    rows = await VideoResource.filter(owner_scope(None if ctx.is_super_admin else team), id=resource_id)
    await ensure_resource_write(ctx, rows)
    if rows:
        await library.cancel_upload(rows[0].team_id, resource_id)
    return ResponseSchema(data=None)


@router.post("/resources/{resource_id}/finalize")
async def finalize(resource_id: int, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    row = await resource_for(None if ctx.is_super_admin else team, resource_id, ready=False, kind=None)
    await ensure_resource_write(ctx, [row])
    return ResponseSchema(data=resource_dict(await library.finalize(row.team_id, resource_id)))


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: int, team: int | None = Depends(library_team), ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=resource_dict(await resource_for(None if ctx.is_super_admin else team, resource_id)))


@router.patch("/resources/{resource_id}")
async def rename(resource_id: int, payload: ResourceRename, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    resource = await resource_for(None if ctx.is_super_admin else team, resource_id)
    await ensure_resource_write(ctx, [resource])
    resource.name = payload.name
    await resource.save(update_fields=["name", "updated_at"])
    return ResponseSchema(data=resource_dict(resource))


@router.post("/move")
async def move(payload: ResourceMove, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    await ensure_resource_write(ctx, await VideoResource.filter(id__in=payload.ids))
    await library.move(None if ctx.is_super_admin else team, payload.ids, payload.folder_id)
    return ResponseSchema(data=None)


@router.post("/delete")
async def delete(payload: ResourceIds, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    await ensure_resource_write(ctx, await VideoResource.filter(id__in=payload.ids))
    return ResponseSchema(data=await library.delete_resources(None if ctx.is_super_admin else team, payload.ids))


@router.get("/folders/{folder_id}/delete-preview")
async def delete_preview(folder_id: int, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    folder_ids, ids = await library.folder_contents(None if ctx.is_super_admin else team, folder_id)
    return ResponseSchema(data={"folder_count": len(folder_ids), "resource_count": len(ids)})


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: int, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    target_team = None if ctx.is_super_admin else team
    return ResponseSchema(data=await library.delete_folder(target_team, folder_id, ctx=ctx))


@router.post("/selection")
async def selection(payload: ResourceSelection, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    config = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value, payload.model_config_id, team_id=team or None)
    caps = capabilities_for(config.video_model_type, config.api_protocol)
    selected = []
    for resource_id in payload.ids:
        resource = await resource_for(None if ctx.is_super_admin else team, resource_id, kind=None)
        validate_resource_model(resource, caps)
        selected.append(reference_dict(resource))
    videos = [item for item in selected if item['type'] == 'video']
    images = [item for item in selected if item['type'] == 'image']
    if len(videos) > caps.max_reference_videos or len(images) > caps.max_reference_images or sum(item.get("duration", 0) for item in videos) > caps.reference_video_total_duration_max + 0.001:
        raise HTTPException(400, detail="所选视频数量或总时长超过当前模型限制")
    return ResponseSchema(data=selected)


@router.post("/import")
async def import_resource(payload: ResourceImport, team: int | None = Depends(library_team), ctx: AuthContext = _EDITOR):
    resource = await library.import_resource(team, ctx.user.id if ctx.user else None, payload)
    return ResponseSchema(data=resource_dict(resource))
