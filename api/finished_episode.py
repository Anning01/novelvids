"""Authenticated episode library and explicit, version-specific publication."""
from contextlib import AsyncExitStack
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from auth.deps import AuthContext, get_auth_context, get_current_user
from controllers import finished_episode
from schemas.finished_episode import FinishedFeatureIn, FinishedPublicationIn
from services.video_editor.finished_media import get_cover
from services.video_enhancement.media import export_media
from utils.messages import localized_message as msg
from utils.response_format import ResponseSchema

router = APIRouter()


async def read_context(request: Request, user=Depends(get_current_user)) -> AuthContext:
    # Active accounts may view published work even when they have no current team.
    try:
        return await get_auth_context(request, user)
    except HTTPException as error:
        if error.status_code != 403:
            raise
        return AuthContext(user=user)


@router.get('')
async def list_episodes(
    scope: Literal['team', 'published', 'featured'] = 'team',
    project_id: int | None = Query(None, gt=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    ctx: AuthContext = Depends(read_context),
):
    return ResponseSchema(data=await finished_episode.list_finished(ctx, scope, project_id, page, page_size))


@router.get('/chapters/{chapter_id}')
async def chapter_item(chapter_id: int, ctx: AuthContext = Depends(read_context)):
    return ResponseSchema(data=await finished_episode.chapter_item(chapter_id, ctx))


@router.get('/chapters/{chapter_id}/versions')
async def list_versions(chapter_id: int, ctx: AuthContext = Depends(read_context)):
    return ResponseSchema(data=await finished_episode.versions(chapter_id, ctx))


@router.put('/chapters/{chapter_id}/publication')
async def publish(chapter_id: int, payload: FinishedPublicationIn, ctx: AuthContext = Depends(get_auth_context)):
    await finished_episode.publish(chapter_id, payload.export_id, ctx, payload.expected_id)
    return ResponseSchema(data={'published_id': payload.export_id})


@router.put('/chapters/{chapter_id}/featured')
async def feature(chapter_id: int, payload: FinishedFeatureIn, ctx: AuthContext = Depends(get_auth_context)):
    await finished_episode.feature(chapter_id, payload.export_id, payload.featured, ctx)
    return ResponseSchema(data={'featured': payload.featured})


@router.get('/versions/{export_id}/cover')
async def cover(export_id: int, ctx: AuthContext = Depends(read_context)):
    export = await finished_episode.accessible_export(export_id, ctx)
    return FileResponse(await get_cover(export), media_type='image/jpeg', headers={'Cache-Control': 'private, no-store'})


@router.get('/versions/{export_id}/video')
async def video(export_id: int, download: bool = False, ctx: AuthContext = Depends(read_context)):
    export = await finished_episode.accessible_export(export_id, ctx)
    return await export_video_response(export, download)


async def export_video_response(export, download: bool = False):
    headers = {'Cache-Control': 'private, no-store'}
    filename = f'episode-{export.chapter_id}-version-{export.id}.mp4' if download else None
    if export.media_ref.startswith('/media/'):
        path = export_media.local_path(export.media_ref)
        if not path.is_file():
            raise HTTPException(404, msg('成片文件不存在或已移除'))
        return FileResponse(path, media_type='video/mp4', filename=filename, headers=headers)
    # Keep upstream object locations private, and stream the result from disk.
    stack = AsyncExitStack()
    try:
        path = await stack.enter_async_context(export_media.materialize(export.media_ref))
        return FileResponse(
            path, media_type='video/mp4', filename=filename, headers=headers,
            background=BackgroundTask(stack.aclose),
        )
    except BaseException:
        await stack.aclose()
        raise
