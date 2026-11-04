"""Publish a project upload once; media bytes are copied outside the write transaction."""
import mimetypes
from fastapi import HTTPException
from auth.deps import ensure_novel_access
from models.novel import Novel
from models.video_edit import EditorAsset
from models.resource_library import ResourcePlacement, VideoResource
from controllers._creation import creation_write
from controllers.resource_library import resource_library_controller as library
from services.resource_catalog import resource_catalog
from services.resource_storage import library_media_storage
from services.video_editor.assets import editor_storage
from utils.messages import localized_message as msg


async def publish_editor_resource(team,ctx,payload):
    source=await EditorAsset.get_or_none(id=payload.source_id)
    if source is None:
        raise HTTPException(404,msg('资源不存在或无权访问'))
    await ensure_novel_access(source.novel_id,ctx)
    novel=await Novel.get(id=source.novel_id).only('id','team_id')
    allowed={'audio':{'bgm','sound'},'sticker':{'sticker'},'video':{'video'}}
    if (novel.team_id or 0)!=team or payload.kind not in allowed.get(source.kind,set()):
        raise HTTPException(422,msg('文件类型不符合所选素材分类'))
    async with creation_write(novel.id):
        publication=await ResourcePlacement.get_or_none(team_id=team,catalog='editor',source_id=source.id)
        if publication:
            previous=await VideoResource.get_or_none(id=publication.media_resource_id,team_id=team)
            if previous:
                if previous.state=='ready':
                    return await resource_catalog.describe(team,'media',previous)
                raise HTTPException(409,msg('此素材正在存入资源库或等待清理，请稍后刷新'))
            await publication.delete()
        reserved=await library.reserve(team,ctx.user.id if ctx.user else None,source.name,payload.folder_id,kind=payload.kind)
        await ResourcePlacement.create(team_id=team,catalog='editor',source_id=source.id,media_resource_id=reserved.id)
    try:
        async with editor_storage.materialize(source.media_ref) as path:
            if path.stat().st_size>library_media_storage.max_bytes:
                raise HTTPException(413,msg('素材大小超过服务端限制'))
            await library_media_storage.put(reserved.storage_ref,path,mimetypes.guess_type(source.name)[0] or 'application/octet-stream')
        reserved=await library.finalize(team,reserved.id)
    except Exception:
        await VideoResource.filter(id=reserved.id,state='uploading').update(state='delete_failed')
        await library.delete_resources(team,[reserved.id])
        raise
    return await resource_catalog.describe(team,'media',reserved)
