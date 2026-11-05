"""Private works management and a separate read-only public projection."""
from contextlib import AsyncExitStack
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from api.finished_episode import export_video_response
from auth.deps import AuthContext, get_auth_context
from controllers import portfolio
from schemas.portfolio import WorkAction, WorkFilter, WorkProfile, WorkSort
from services.oss import normalize_media_url, oss
from services.video_editor.finished_media import get_cover
from utils.messages import localized_message as msg
from utils.response_format import ResponseSchema

router = APIRouter()
PRIVATE_HEADERS = {'Cache-Control': 'private, no-store'}


@router.get('')
async def list_works(
    status: WorkFilter = 'all', search: str = Query('', max_length=255),
    category: str = Query('', max_length=80), producer_id: int | None = Query(None, gt=0),
    sort: WorkSort = 'recent', project_id: int | None = Query(None, gt=0),
    page: int = Query(1, ge=1), page_size: int = Query(18, ge=1, le=50),
    ctx: AuthContext = Depends(get_auth_context),
):
    return ResponseSchema(data=await portfolio.list_works(
        ctx, status=status, search=search, category=category, producer_id=producer_id,
        sort=sort, project_id=project_id, page=page, page_size=page_size,
    ))


def _public_error(error: HTTPException) -> JSONResponse:
    body = ResponseSchema(code=error.status_code, message=str(error.detail))
    return JSONResponse(body.model_dump(), status_code=error.status_code, headers=PRIVATE_HEADERS)


@router.get('/public/{project_id}')
async def public_detail(project_id: int, response: Response):
    try:
        work = await portfolio.detail(project_id)
    except HTTPException as error:
        return _public_error(error)
    response.headers.update(PRIVATE_HEADERS)
    return ResponseSchema(data=work.model_dump(exclude={'production_seconds', 'recorded_cost', 'cost_scope'}))


@router.get('/public/{project_id}/episodes/{export_id}/{kind}')
async def public_media(project_id: int, export_id: int, kind: Literal['cover', 'video'], request: Request):
    try:
        export = await portfolio.public_export(project_id, export_id)
        if kind == 'cover':
            return FileResponse(await get_cover(export), media_type='image/jpeg', headers=PRIVATE_HEADERS)
        return await _public_video(export, request.headers.get('range'))
    except HTTPException as error:
        return _public_error(error)


async def _public_video(export, byte_range: str | None):
    reference = normalize_media_url(export.media_ref)
    if not oss.enabled or not reference or not reference.startswith('uploads/'):
        return await export_video_response(export)

    stack = AsyncExitStack()
    try:
        upstream = await stack.enter_async_context(oss.open_download(reference, byte_range=byte_range))
        if upstream.status_code == 404:
            raise HTTPException(404, msg('成片文件不存在或已移除'))
        if upstream.status_code not in (200, 206, 416):
            raise HTTPException(502, msg('作品播放失败'))
        headers = {**PRIVATE_HEADERS, 'Accept-Ranges': 'bytes'}
        if upstream.status_code == 416:
            if 'content-range' in upstream.headers:
                headers['Content-Range'] = upstream.headers['content-range']
            await stack.aclose()
            return Response(status_code=416, headers=headers)
        for name in ('content-length', 'content-range'):
            if name in upstream.headers:
                headers[name] = upstream.headers[name]

        async def stream():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await stack.aclose()

        return StreamingResponse(
            stream(), status_code=upstream.status_code, media_type='video/mp4',
            headers=headers, background=BackgroundTask(stack.aclose),
        )
    except httpx.HTTPError:
        await stack.aclose()
        raise HTTPException(502, msg('作品播放失败')) from None
    except BaseException:
        await stack.aclose()
        raise


@router.get('/{project_id}')
async def detail(project_id: int, ctx: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(data=await portfolio.detail(project_id, ctx, include_costs=True))


@router.put('/{project_id}')
async def save_profile(project_id: int, payload: WorkProfile, ctx: AuthContext = Depends(get_auth_context)):
    await portfolio.save_profile(project_id, payload, ctx)
    return ResponseSchema(data=await portfolio.detail(project_id, ctx, include_costs=True))


@router.put('/{project_id}/status')
async def change_status(project_id: int, payload: WorkAction, ctx: AuthContext = Depends(get_auth_context)):
    await portfolio.change_status(project_id, payload, ctx)
    return ResponseSchema(data=await portfolio.detail(project_id, ctx, include_costs=True))
