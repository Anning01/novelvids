from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict

from schemas._base import BaseResponse
from utils.enums import AiTaskTypeEnum, ImageModelTypeEnum, VideoGenerationModelTypeEnum
from utils.image_protocol import ImageApiProtocol


# --- 核心业务属性 ---

class AiModelConfigProperties(BaseModel):
    """AI 模型配置属性。"""

    task_type: Optional[int] = Field(None, description=AiTaskTypeEnum.__doc__)
    task_types: Optional[list[int]] = Field(None, description="模型支持的任务类型列表")
    name: Optional[str] = Field(None, description="配置名称", max_length=100)
    base_url: Optional[str] = Field(None, description="API 地址", max_length=500)
    api_key: Optional[str] = Field(None, description="API Key", max_length=500)
    model: Optional[str] = Field(None, description="模型名称", max_length=200)
    api_protocol: ImageApiProtocol = Field(
        ImageApiProtocol.openai_compatible,
        description="接口协议；生图任务可选择 OpenAI、OpenRouter 兼容或火山方舟",
    )
    image_model_type: Optional[ImageModelTypeEnum] = Field(
        None,
        description="生图模型能力类型，仅支持 Seedream 5 Lite/Pro 与 GPT Image 2",
    )
    video_model_type: Optional[VideoGenerationModelTypeEnum] = Field(
        None,
        description="视频生成模型能力类型，仅支持 Seedance 2.0、2.0 Fast、2.0 Mini 与 2.5",
    )
    is_active: Optional[bool] = Field(None, description="是否启用")
    concurrency: Optional[int] = Field(None, description="并发数", ge=1)
    supports_json_output: Optional[bool] = Field(
        False,
        description="是否支持 response_format=json_object",
    )
    max_context_characters: Optional[int] = Field(
        None,
        description="四层业务消息允许的最大总字符数",
        ge=1,
    )


# --- 输入 Schema ---

class AiModelConfigCreate(AiModelConfigProperties):
    """创建请求：必填字段。"""

    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    task_types: list[int] = Field(default_factory=list, description="模型支持的任务类型列表")
    name: str = Field(..., description="配置名称", max_length=100)
    base_url: str = Field(..., description="API 地址", max_length=500)
    api_key: str = Field(..., description="API Key", max_length=500)
    model: str = Field(..., description="模型名称", max_length=200)


class AiModelConfigUpdate(AiModelConfigCreate):
    """全量更新：同创建。"""
    pass


class AiModelConfigPatch(AiModelConfigProperties):
    """局部更新：全字段可选。"""
    pass


# --- 输出 Schema ---

class AiModelConfigOut(AiModelConfigProperties, BaseResponse):
    """配置输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="配置ID")
    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    task_types: list[int] = Field(default_factory=list, description="模型支持的任务类型列表")
    name: str = Field(..., description="配置名称")
    is_active: bool = Field(..., description="是否启用")
    concurrency: int = Field(..., description="并发数")
    supports_json_output: bool = Field(False, description="是否支持结构化 JSON 输出")
    max_context_characters: Optional[int] = Field(
        None,
        description="四层业务消息允许的最大总字符数",
        ge=1,
    )
    api_protocol: ImageApiProtocol = Field(
        ImageApiProtocol.openai_compatible,
        description="模型接口协议",
    )


class ImageGenerationCapabilitiesOut(BaseModel):
    clarities: list[str]
    aspect_ratios: list[str]
    output_formats: list[str]
    generation_counts: list[int]
    default_clarity: str
    default_aspect_ratio: str
    default_output_format: str
    default_generation_count: int


class ImageGenerationModelOut(BaseModel):
    config_id: int
    name: str
    model: str
    model_type: ImageModelTypeEnum
    concurrency: int
    capabilities: ImageGenerationCapabilitiesOut


class VideoGenerationCapabilitiesOut(BaseModel):
    resolutions: list[str] = Field(..., description="支持的视频分辨率")
    aspect_ratios: list[str] = Field(..., description="支持的视频宽高比")
    aspect_ratios_by_mode: dict[str, list[str]] = Field(..., description="不同生成方式支持的视频宽高比")
    output_formats: list[str] = Field(..., description="支持的视频输出格式")
    generation_modes: list[str] = Field(..., description="支持的视频生成方式")
    duration_min: int = Field(..., description="最短生成时长（秒）")
    duration_max: int = Field(..., description="最长生成时长（秒）")
    supports_auto_duration: bool = Field(..., description="是否支持自动时长 -1")
    supports_audio: bool = Field(..., description="是否支持生成同步音频")
    max_reference_images: int = Field(..., description="最多参考图片数量")
    max_reference_videos: int = Field(..., description="最多参考视频数量")
    max_reference_audios: int = Field(..., description="最多参考音频数量")
    reference_video_duration_max: int = Field(..., description="单个参考视频最长时长（秒）")
    reference_video_total_duration_max: int = Field(..., description="参考视频总时长上限（秒）")
    reference_audio_duration_max: int = Field(..., description="单个参考音频最长时长（秒）")
    reference_audio_total_duration_max: int = Field(..., description="参考音频总时长上限（秒）")
    supports_return_last_frame: bool = Field(..., description="是否支持返回生成视频尾帧")
    reference_image_formats: list[str] = Field(..., description="参考图片格式")
    reference_video_formats: list[str] = Field(..., description="参考视频容器格式")
    reference_video_codecs: list[str] = Field(..., description="参考视频编码")
    reference_video_audio_codecs: list[str] = Field(..., description="参考视频音轨编码")
    reference_video_resolutions: list[str] = Field(..., description="参考视频分辨率档位")
    reference_image_max_size_mb: int = Field(..., description="单张参考图片大小上限")
    reference_video_max_size_mb: int = Field(..., description="单个参考视频大小上限")
    reference_media_duration_min: int = Field(..., description="参考音视频最短时长")
    reference_media_ratio_min: float = Field(..., description="参考媒体最小宽高比")
    reference_media_ratio_max: float = Field(..., description="参考媒体最大宽高比")
    reference_media_side_min: int = Field(..., description="参考媒体最短边长")
    reference_media_side_max: int = Field(..., description="参考媒体最长边长")
    reference_video_pixels_min: int = Field(..., description="参考视频最小像素数")
    reference_video_pixels_max: int = Field(..., description="参考视频最大像素数")
    reference_video_fps_min: int = Field(..., description="参考视频最低帧率")
    reference_video_fps_max: int = Field(..., description="参考视频最高帧率")
    default_resolution: str = Field(..., description="默认视频分辨率")
    default_aspect_ratio: str = Field(..., description="默认视频宽高比")
    default_output_format: str = Field(..., description="默认视频格式")
    default_generate_audio: bool = Field(..., description="默认是否生成同步音频")


class VideoGenerationModelOut(BaseModel):
    config_id: int = Field(..., description="模型配置ID")
    name: str = Field(..., description="配置名称")
    model: str = Field(..., description="供应商模型ID")
    model_type: VideoGenerationModelTypeEnum = Field(..., description="视频生成模型类型")
    concurrency: int = Field(..., description="并发数")
    capabilities: VideoGenerationCapabilitiesOut = Field(..., description="视频生成参数能力")


class GeneralConfigUpdate(BaseModel):
    """应用级通用配置更新请求。"""

    prompt_language: Literal["zh", "en"] = Field(
        ...,
        description="新生成的图片提示词与镜头提示词语言",
    )


class GeneralConfigOut(GeneralConfigUpdate, BaseResponse):
    """应用级通用配置输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="配置ID")
