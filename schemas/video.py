from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Literal, Optional
from schemas._base import BaseResponse
from utils.enums import VideoModelTypeEnum, TaskStatusEnum


# --- 输入 Schema ---

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


# --- 输出 Schema ---

class VideoBriefOut(BaseResponse):
    """列表输出：简要信息"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="视频ID")
    model_type: Optional[VideoModelTypeEnum] = Field(None, description="视频模型类型")
    url: Optional[str] = Field(None, description="视频URL")
    status: Optional[TaskStatusEnum] = Field(None, description="状态")
    metadata: Optional[Any] = Field(None, description="元数据")


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


class VideoQueryOut(BaseModel):
    """查询视频生成状态的结果"""
    id: int = Field(..., description="视频ID")
    scene_id: int = Field(..., description="所属分镜ID")
    status: TaskStatusEnum = Field(..., description="状态")
    progress: Optional[int] = Field(None, description="进度百分比")
    url: Optional[str] = Field(None, description="视频URL")
    metadata: Optional[Any] = Field(None, description="元数据")


# --- 合并视频 Schema ---

class VideoMergeRequest(BaseModel):
    """视频合并请求"""
    chapter_id: int = Field(..., description="章节ID")


class VideoMergeOut(BaseModel):
    """视频合并结果"""
    chapter_id: int = Field(..., description="章节ID")
    merged_url: str = Field(..., description="合并后的视频URL")
    video_count: int = Field(..., description="合并的视频数量")
    total_duration: float = Field(..., description="视频总时长（秒）")
