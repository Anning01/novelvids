from fastapi import APIRouter, Depends

from controllers.video import video_controller
from schemas.video import (
    VideoBriefOut,
    VideoGenerateRequest,
    VideoOut,
    VideoQueryOut,
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
