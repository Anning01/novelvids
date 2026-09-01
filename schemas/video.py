from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Any, Literal, Optional
from schemas._base import BaseResponse
from utils.enums import VideoModelTypeEnum, TaskStatusEnum
from services.oss import resolve_media_url


def _resolve_video_metadata(metadata: Any) -> None:
    """解析 video.metadata 中持久化的媒体引用（首尾帧与参考素材）。

    后端把尾帧等媒体落库为 OSS key（uploads/...），读取时统一解析为公共 URL。
    """
    if not isinstance(metadata, dict):
        return
    for key in (
        "first_frame_url",
        "last_frame_url",
        "poster_url",
        "poster_thumbnail_url",
    ):
        raw = metadata.get(key)
        if isinstance(raw, str) and raw:
            metadata[key] = resolve_media_url(raw) or raw
    last_frame_reference = metadata.get("last_frame_reference")
    if isinstance(last_frame_reference, dict):
        raw = last_frame_reference.get("url")
        if isinstance(raw, str) and raw:
            last_frame_reference["url"] = resolve_media_url(raw) or raw
    reference_media = metadata.get("reference_media")
    if isinstance(reference_media, list):
        for item in reference_media:
            if isinstance(item, dict):
                raw = item.get("url")
                if isinstance(raw, str) and raw:
                    item["url"] = resolve_media_url(raw) or raw


# --- 输入 Schema ---

class VideoReferenceMedia(BaseModel):
    """已上传并通过模型能力校验的参考素材。"""
    model_config = ConfigDict(extra="forbid")

    type: Literal["image", "video"]
    url: str = Field(..., min_length=1, max_length=2000)
    mention_url: Optional[str] = Field(
        None,
        min_length=1,
        max_length=2000,
        description="用于 Prompt 引用匹配的稳定原始地址；展示与请求仍使用 url",
    )
    name: Optional[str] = Field(None, max_length=255)
    content_type: Optional[str] = Field(None, max_length=100)
    size_bytes: Optional[int] = Field(None, ge=0)
    width: Optional[int] = Field(None, ge=1)
    height: Optional[int] = Field(None, ge=1)
    duration: Optional[float] = Field(None, ge=0)
    fps: Optional[float] = Field(None, ge=0)
    codec: Optional[str] = Field(None, max_length=50)


class VideoGenerateRequest(BaseModel):
    """提交视频生成请求"""
    model_config = ConfigDict(extra="forbid")

    scene_id: int = Field(..., description="分镜ID")
    model_config_id: int = Field(..., description="后台已启用的视频模型配置ID", ge=1)
    generation_mode: Literal["reference", "keyframes"] = Field("reference", description="参考图或首尾帧生成模式")
    first_frame_url: Optional[str] = Field(None, description="首帧图片地址")
    last_frame_url: Optional[str] = Field(None, description="尾帧图片地址")
    resolution: Optional[str] = Field(None, description="视频分辨率，由所选模型能力校验")
    aspect_ratio: Optional[str] = Field(None, description="视频宽高比，由所选模型能力校验")
    duration: Optional[int] = Field(None, description="视频时长（秒），留空使用分镜时长")
    output_format: Optional[str] = Field(None, description="视频输出格式")
    generate_audio: Optional[bool] = Field(None, description="是否生成同步音频")
    return_last_frame: Optional[bool] = Field(False, description="是否返回尾帧并注入下一分镜参考图")
    reference_media: list[VideoReferenceMedia] = Field(default_factory=list, description="用户上传的参考图片与视频")


# --- 输出 Schema ---

class VideoBriefOut(BaseResponse):
    """列表输出：简要信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="视频ID")
    model_type: Optional[VideoModelTypeEnum] =  Field(None, description="视频模型类型")
    url: Optional[str] = Field(None, description="视频URL")
    status: Optional[TaskStatusEnum] = Field(None, description="状态")
    metadata: Optional[Any] = Field(None, description="元数据")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.url = resolve_media_url(self.url)
        _resolve_video_metadata(self.metadata)
        return self


class VideoOut(BaseResponse):
    """详情输出：完整信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="视频ID")
    scene_id: int = Field(..., description="分镜ID")
    model_type: Optional[VideoModelTypeEnum] = Field(None, description="视频模型类型")
    external_task_id: Optional[str] = Field(None, description="外部任务ID")
    url: Optional[str] = Field(None, description="视频URL")
    status: Optional[TaskStatusEnum] = Field(None, description="状态")
    metadata: Optional[Any] = Field(None, description="元数据")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.url = resolve_media_url(self.url)
        _resolve_video_metadata(self.metadata)
        return self


class VideoQueryOut(BaseModel):
    """查询视频生成状态的结果"""
    id: int = Field(..., description="视频ID")
    scene_id: int = Field(..., description="所属分镜ID")
    status: TaskStatusEnum = Field(..., description="状态")
    progress: Optional[int] = Field(None, description="进度百分比")
    url: Optional[str] = Field(None, description="视频URL")
    metadata: Optional[Any] = Field(None, description="元数据")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.url = resolve_media_url(self.url)
        _resolve_video_metadata(self.metadata)
        return self


# --- 合并视频 Schema ---

class VideoMergeRequest(BaseModel):
    """视频合并请求"""
    chapter_id: int = Field(..., description="章节ID")
    strict: bool = Field(False, description="是否要求每个分镜的当前版本均已完成")


class VideoMergeOut(BaseModel):
    """视频合并结果"""
    chapter_id: int = Field(..., description="章节ID")
    merged_url: str = Field(..., description="合并后的视频URL")
    poster_url: Optional[str] = Field(None, description="成片预览海报")
    poster_thumbnail_url: Optional[str] = Field(None, description="成片缩略海报")
    video_count: int = Field(..., description="合并的视频数量")
    total_duration: float = Field(..., description="视频总时长（秒）")

    @model_validator(mode="after")
    def _resolve_media(self):
        self.merged_url = resolve_media_url(self.merged_url) or self.merged_url
        self.poster_url = resolve_media_url(self.poster_url)
        self.poster_thumbnail_url = resolve_media_url(self.poster_thumbnail_url)
        return self
