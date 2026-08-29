from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from pydantic import BaseModel, Field

from auth.deps import (
    AuthContext,
    get_auth_context,
    require_chapter_access,
    require_roles,
    require_scene_access,
    require_team_access,
    require_video_access,
)
from controllers.video import video_controller
from models.video import Video
from schemas.video import (
    VideoBriefOut,
    VideoGenerateRequest,
    VideoOut,
    VideoQueryOut,
    VideoMergeRequest,
    VideoMergeOut,
    VideoReferenceMedia,
)
from controllers.config import ai_model_config_controller
from services.video.capabilities import capabilities_for
from services.video.reference_media import save_reference_upload
from utils.enums import AiTaskTypeEnum
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()

_EDITOR = Depends(require_roles("admin", "creator"))


@router.post("/generate/", summary="提交视频生成", response_model=ResponseSchema[VideoOut])
async def generate_video(
    req: VideoGenerateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    """提交视频生成请求，返回 Video 记录"""
    await require_scene_access(req.scene_id, ctx)
    video = await video_controller.generate(
        req,
        media_base_url=str(request.base_url).rstrip("/"),
        team_id=ctx.team_id,
        user_id=ctx.user.id if ctx.user else None,
    )
    return ResponseSchema(data=video)


class VideoReferenceOssFinalizeIn(BaseModel):
    model_config_id: int = Field(ge=1)
    key: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=255)


@router.post("/reference/oss-finalize", summary="OSS 直传后登记视频参考素材（不再经过服务器）")
async def finalize_video_reference_oss(
    payload: VideoReferenceOssFinalizeIn,
    _: AuthContext = _EDITOR,
):
    from services.oss import oss
    from services.video.reference_media import media_kind_for_extension

    if not oss.enabled:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="未启用对象存储")
    config = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.video.value,
        payload.model_config_id,
    )
    capabilities = capabilities_for(config.video_model_type)
    kind = media_kind_for_extension(payload.filename, capabilities)
    url = oss.public_url(payload.key)
    return ResponseSchema(
        data={
            "type": kind,
            "url": url,
            "name": payload.filename,
            "content_type": payload.filename.rsplit(".", 1)[-1].lower(),
        }
    )


@router.post("/reference/upload", summary="上传视频生成参考素材", response_model=ResponseSchema[VideoReferenceMedia])
async def upload_video_reference(
    model_config_id: int = Form(..., ge=1),
    file: UploadFile = File(...),
    _: AuthContext = _EDITOR,
):
    config = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.video.value,
        model_config_id,
    )
    capabilities = capabilities_for(config.video_model_type)
    return ResponseSchema(data=await save_reference_upload(file, capabilities))


@router.get("/query/{video_id}", summary="查询视频生成状态", response_model=ResponseSchema[VideoQueryOut])
async def query_video(
    video_id: int,
    _: AuthContext = Depends(require_video_access),
):
    """轮询查询视频生成进度"""
    video = await video_controller.query_status(video_id)
    return ResponseSchema(data=video)


@router.get(
    "/scene/{scene_id}/generation-history",
    summary="获取分镜视频生成记录",
    response_model=ResponseSchema[list[VideoOut]],
)
async def get_video_generation_history(
    scene_id: int,
    _: AuthContext = Depends(require_scene_access),
):
    videos = await video_controller.generation_history(scene_id)
    return ResponseSchema(data=[VideoOut.model_validate(video) for video in videos])


@router.post(
    "/{video_id}/select-current",
    summary="将视频生成记录设为当前版本",
    response_model=ResponseSchema[VideoOut],
)
async def select_current_video(
    video_id: int,
    _: AuthContext = Depends(require_video_access),
    __: AuthContext = _EDITOR,
):
    video = await video_controller.select_current(video_id)
    return ResponseSchema(data=VideoOut.model_validate(video))


@router.get("", summary="获取视频列表", response_model=ResponseSchema[PaginationResponse[VideoBriefOut]])
async def get_video_list(
    params: QueryParams = Depends(get_list_params),
    ctx: AuthContext = Depends(get_auth_context),
):
    base_query = None
    if ctx.team_id is not None:
        base_query = Video.filter(scene__chapter__novel__team_id=ctx.team_id)
    videos = await video_controller.list(params, VideoBriefOut, base_query=base_query)
    return ResponseSchema(data=videos)


@router.get("/{video_id}", summary="获取视频详情", response_model=ResponseSchema[VideoOut])
async def get_video(
    video_id: int,
    _: AuthContext = Depends(require_video_access),
):
    video = await video_controller.get(video_id)
    return ResponseSchema(data=video)


@router.delete("/{video_id}", summary="删除视频", response_model=ResponseSchema)
async def delete_video(
    video_id: int,
    _: AuthContext = Depends(require_video_access),
    __: AuthContext = _EDITOR,
):
    await video_controller.remove(video_id)
    return ResponseSchema()


@router.post("/merge", summary="合并章节视频", response_model=ResponseSchema[VideoMergeOut])
async def merge_chapter_videos(
    req: VideoMergeRequest,
    ctx: AuthContext = Depends(get_auth_context),
    _: AuthContext = _EDITOR,
):
    await require_chapter_access(req.chapter_id, ctx)
    result = await video_controller.merge_chapter_videos(req.chapter_id, strict=req.strict)
    return ResponseSchema(data=result)


@router.get("/merge/{chapter_id}", summary="查询章节合并视频")
async def get_merged_video(
    chapter_id: int,
    _: AuthContext = Depends(require_chapter_access),
):
    result = await video_controller.get_merged_video(chapter_id)
    if result is None:
        return ResponseSchema(code=1, data=None, message="未找到合并视频")
    return ResponseSchema(data=result)


@router.get("/chapter/{chapter_id}", summary="获取章节下所有分镜的视频")
async def get_chapter_videos(
    chapter_id: int,
    _: AuthContext = Depends(require_chapter_access),
):
    videos = await video_controller.get_chapter_videos(chapter_id)
    return ResponseSchema(data=videos)

@router.get("/novel/{novel_id}", summary="获取小说下的所有视频")
async def get_novel_videos(
    novel_id: int,
    _: AuthContext = Depends(require_team_access),
):
    videos = await video_controller.get_novel_videos(novel_id)
    return ResponseSchema(data=videos)
