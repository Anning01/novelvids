from fastapi import APIRouter, Depends

from controllers.video import video_controller
from schemas.video import (
    VideoBriefOut,
    VideoGenerateRequest,
    VideoOut,
    VideoQueryOut,
    VideoMergeRequest,
    VideoMergeOut,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.post("/generate/", summary="提交视频生成", response_model=ResponseSchema[VideoOut])
async def generate_video(req: VideoGenerateRequest):
    """提交视频生成请求，返回 Video 记录"""
    video = await video_controller.generate(req)
    return ResponseSchema(data=video)


@router.get("/query/{video_id}", summary="查询视频生成状态", response_model=ResponseSchema[VideoQueryOut])
async def query_video(video_id: int):
    """轮询查询视频生成进度"""
    video = await video_controller.query_status(video_id)
    return ResponseSchema(data=video)


@router.get("", summary="获取视频列表", response_model=ResponseSchema[PaginationResponse[VideoBriefOut]])
async def get_video_list(params: QueryParams = Depends(get_list_params)):
    videos = await video_controller.list(params, VideoBriefOut)
    return ResponseSchema(data=videos)


@router.get("/{video_id}", summary="获取视频详情", response_model=ResponseSchema[VideoOut])
async def get_video(video_id: int):
    video = await video_controller.get(video_id)
    return ResponseSchema(data=video)


@router.delete("/{video_id}", summary="删除视频", response_model=ResponseSchema)
async def delete_video(video_id: int):
    await video_controller.remove(video_id)
    return ResponseSchema()


@router.post("/merge", summary="合并章节视频", response_model=ResponseSchema[VideoMergeOut])
async def merge_chapter_videos(req: VideoMergeRequest):
    result = await video_controller.merge_chapter_videos(req.chapter_id)
    return ResponseSchema(data=result)


@router.get("/merge/{chapter_id}", summary="查询章节合并视频")
async def get_merged_video(chapter_id: int):
    result = await video_controller.get_merged_video(chapter_id)
    if result is None:
        return ResponseSchema(code=1, data=None, message="未找到合并视频")
    return ResponseSchema(data=result)


@router.get("/chapter/{chapter_id}", summary="获取章节下所有分镜的视频")
async def get_chapter_videos(chapter_id: int):
    videos = await video_controller.get_chapter_videos(chapter_id)
    return ResponseSchema(data=videos)

@router.get("/novel/{novel_id}", summary="获取小说下的所有视频")
async def get_novel_videos(novel_id: int):
    videos = await video_controller.get_novel_videos(novel_id)
    return ResponseSchema(data=videos)