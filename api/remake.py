from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from auth.deps import (
    AuthContext,
    ensure_novel_access,
    get_auth_context,
    require_roles,
)
from exceptions.remake import RemakeError
from models.ai_task import AiTask
from models.novel import Novel
from models.remake_source import RemakeSource
from prompts.styles import list_remake_styles
from schemas.remake import RemakeProjectCreate, RemakeSourceOut
from services.project_config import project_aspect_ratios, project_resolutions
from services.ai_task_executor import ai_task_executor
from services.remake.media import (
    ALLOWED_REMAKE_EXTENSIONS,
    MAX_REMAKE_BYTES,
    MAX_REMAKE_DURATION_SECONDS,
)
from services.remake.history import remake_history_catalog
from services.remake.episodes import EPISODE_PATTERN_EXAMPLES
from services.remake.dispatcher import remake_task_dispatcher
from services.remake.projects import remake_project_service
from services.remake.progress import remake_progress_service
from services.remake.uploads import remake_upload_service
from utils.enums import TaskStatusEnum
from utils.response_format import ResponseSchema

router = APIRouter()
_EDITOR = Depends(require_roles("admin", "creator"))


class RemakeUploadFinalizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_key: str = Field(..., min_length=1, max_length=500)
    original_filename: str = Field(..., min_length=1, max_length=255)


def _upload_data(upload) -> dict:
    return {
        "upload_token": str(upload.id),
        "storage_provider": upload.storage_provider,
        "object_key": upload.object_key,
        "original_filename": upload.original_filename,
        "mime_type": upload.mime_type,
        "size_bytes": upload.size_bytes,
        "duration_seconds": upload.duration_seconds,
        "width": upload.width,
        "height": upload.height,
        "container_format": upload.container_format,
        "checksum": upload.checksum,
        "status": upload.status,
        "expires_at": upload.expires_at,
    }


@router.get("/capabilities", summary="获取重制工坊能力配置")
async def get_capabilities(_: AuthContext = Depends(get_auth_context)):
    return ResponseSchema(
        data={
            "media": {
                "extensions": [
                    extension
                    for extension in ("mp4", "mov")
                    if f".{extension}" in ALLOWED_REMAKE_EXTENSIONS
                ],
                "max_bytes": MAX_REMAKE_BYTES,
                "max_duration_seconds": int(MAX_REMAKE_DURATION_SECONDS),
            },
            "aspect_ratios": list(project_aspect_ratios()),
            "resolutions": list(project_resolutions()),
            "styles": list_remake_styles(),
            "episode_patterns": list(EPISODE_PATTERN_EXAMPLES),
            "source_modes": {
                "single_upload": True,
                "folder_upload": True,
                "history": True,
            },
        }
    )


@router.get("/history/projects", summary="获取可重制历史项目")
async def list_history_projects(
    keyword: str = Query("", max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AuthContext = Depends(get_auth_context),
):
    result = await remake_history_catalog.list_projects(
        team_id=ctx.team_id,
        allow_all=ctx.user is None or ctx.is_super_admin,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ResponseSchema(data=result)


@router.get(
    "/history/projects/{novel_id}/episodes",
    summary="获取历史项目剧集可重制状态",
)
async def list_history_episodes(
    novel_id: int,
    ctx: AuthContext = Depends(get_auth_context),
):
    novel = await Novel.get_or_none(id=novel_id)
    if novel is None or novel.workflow_kind != "script":
        raise RemakeError(404, "REMAKE_HISTORY_PROJECT_NOT_FOUND", "历史项目不存在")
    if (
        ctx.user is not None
        and not ctx.is_super_admin
        and novel.team_id != ctx.team_id
    ):
        raise RemakeError(
            403,
            "REMAKE_HISTORY_PROJECT_FORBIDDEN",
            "无权访问该历史项目",
        )
    return ResponseSchema(data=await remake_history_catalog.list_episodes(novel.id))


@router.get("/uploads/policy", summary="获取重制视频 OSS 直传策略")
async def get_upload_policy(
    filename: str = Query(..., min_length=1, max_length=255),
    content_type: str = Query("application/octet-stream", max_length=120),
    size_bytes: int = Query(..., gt=0),
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    if not remake_upload_service.provider.enabled:
        return ResponseSchema(data={"direct": False})
    upload, policy = await remake_upload_service.create_policy(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(
        data={
            "direct": True,
            "provider": upload.storage_provider,
            "upload_token": str(upload.id),
            "object_key": upload.object_key,
            "upload_url": policy["url"],
            "fields": policy["fields"],
            "expires_at": upload.expires_at,
        }
    )


@router.post("/uploads", summary="本地暂存单个重制来源视频")
async def upload_video(
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    upload = await remake_upload_service.stage_local(
        file,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(data=_upload_data(upload))


@router.post("/uploads/finalize", summary="完成 OSS 重制来源终局校验")
async def finalize_upload(
    payload: RemakeUploadFinalizeIn,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    if not remake_upload_service.provider.enabled:
        raise RemakeError(409, "REMAKE_UPLOAD_NOT_READY", "当前环境使用本地上传")
    upload = await remake_upload_service.finalize_oss(
        object_key=payload.object_key,
        original_filename=payload.original_filename,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(data=_upload_data(upload))


@router.delete("/uploads/{upload_token}", summary="释放未提交的重制来源")
async def release_upload(
    upload_token: UUID,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    await remake_upload_service.release(
        upload_token,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema()


@router.post("/projects", summary="幂等创建重制项目")
async def create_project(
    payload: RemakeProjectCreate,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    result = await remake_project_service.create(
        payload,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
        allow_all_history=ctx.user is None or ctx.is_super_admin,
    )
    queued_tasks = []
    for item in result["sources"]:
        task = await AiTask.get_or_none(id=item["task_id"])
        if task is not None and task.status == TaskStatusEnum.queued.value:
            queued_tasks.append(task)
    if queued_tasks:
        background_tasks.add_task(remake_task_dispatcher.run, queued_tasks)
    return ResponseSchema(data=result)


async def _get_remake_novel(novel_id: int, ctx: AuthContext) -> Novel:
    await ensure_novel_access(novel_id, ctx)
    novel = await Novel.get_or_none(id=novel_id)
    if novel is None or novel.workflow_kind != "remake":
        raise RemakeError(404, "REMAKE_PROJECT_NOT_FOUND", "重制项目不存在")
    return novel


@router.get("/projects/{novel_id}", summary="获取重制项目")
async def get_project(
    novel_id: int,
    ctx: AuthContext = Depends(get_auth_context),
):
    novel = await _get_remake_novel(novel_id, ctx)
    progress = await remake_progress_service.snapshot(novel)
    return ResponseSchema(
        data={
            "id": novel.id,
            "name": novel.name,
            "workflow_kind": novel.workflow_kind,
            "aspect_ratio": novel.aspect_ratio,
            "resolution": novel.resolution,
            "style_key": novel.style_key,
            "custom_style_prompt": novel.custom_style_prompt,
            "total_chapters": novel.total_chapters,
            "aggregate_status": progress["aggregate_status"],
            "source_summary": progress["source_summary"],
            "created_at": novel.created_at,
            "updated_at": novel.updated_at,
        }
    )


@router.get(
    "/projects/{novel_id}/progress",
    summary="获取重制项目拆解进度快照",
)
async def get_project_progress(
    novel_id: int,
    ctx: AuthContext = Depends(get_auth_context),
):
    novel = await _get_remake_novel(novel_id, ctx)
    return ResponseSchema(data=await remake_progress_service.snapshot(novel))


@router.get(
    "/projects/{novel_id}/events",
    summary="订阅重制项目拆解进度事件",
)
async def stream_project_progress(
    novel_id: int,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
):
    novel = await _get_remake_novel(novel_id, ctx)

    async def event_stream():
        last_version: str | None = None
        while True:
            snapshot = await remake_progress_service.snapshot(novel)
            if snapshot["updated_at"] != last_version:
                event = (
                    "complete"
                    if snapshot["aggregate_status"] == "completed"
                    else "terminal"
                    if snapshot["terminal"]
                    else "progress"
                )
                yield (
                    f"id: {snapshot['updated_at']}\n"
                    f"event: {event}\n"
                    f"data: {json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))}\n\n"
                )
                last_version = snapshot["updated_at"]
            if snapshot["terminal"] or await request.is_disconnected():
                break
            yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{novel_id}/sources", summary="获取重制项目来源")
async def get_project_sources(
    novel_id: int,
    ctx: AuthContext = Depends(get_auth_context),
):
    await _get_remake_novel(novel_id, ctx)
    sources = await RemakeSource.filter(novel_id=novel_id).order_by("episode_number")
    return ResponseSchema(
        data=[RemakeSourceOut.model_validate(source) for source in sources]
    )


@router.post(
    "/projects/{novel_id}/sources/{source_id}/retry",
    summary="重试失败的重制拆解任务",
)
async def retry_source(
    novel_id: int,
    source_id: int,
    background_tasks: BackgroundTasks,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    await _get_remake_novel(novel_id, ctx)
    source = await RemakeSource.get_or_none(id=source_id, novel_id=novel_id)
    if source is None:
        raise RemakeError(404, "REMAKE_SOURCE_NOT_FOUND", "重制来源不存在")
    result = await remake_project_service.retry(
        source.id,
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    task = await AiTask.get(id=result["task_id"])
    background_tasks.add_task(ai_task_executor.run, task)
    return ResponseSchema(data=result)
