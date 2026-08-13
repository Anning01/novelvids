"""后台定义的视频模型能力与请求参数校验。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException

from utils.enums import VideoGenerationModelTypeEnum
from utils.image_protocol import ImageApiProtocol


COMMON_RATIOS = ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive")
GENERATION_MODES = ("reference", "keyframes")


@dataclass(frozen=True)
class VideoModelCapabilities:
    resolutions: tuple[str, ...]
    aspect_ratios: tuple[str, ...]
    aspect_ratios_by_mode: dict[str, tuple[str, ...]]
    output_formats: tuple[str, ...]
    generation_modes: tuple[str, ...]
    duration_min: int
    duration_max: int
    supports_auto_duration: bool
    supports_audio: bool
    max_reference_images: int
    default_resolution: str = "720p"
    default_aspect_ratio: str = "adaptive"
    default_output_format: str = "mp4"
    default_generate_audio: bool = True

    def public_dict(self) -> dict:
        return {
            "resolutions": list(self.resolutions),
            "aspect_ratios": list(self.aspect_ratios),
            "aspect_ratios_by_mode": {
                mode: list(values)
                for mode, values in self.aspect_ratios_by_mode.items()
            },
            "output_formats": list(self.output_formats),
            "generation_modes": list(self.generation_modes),
            "duration_min": self.duration_min,
            "duration_max": self.duration_max,
            "supports_auto_duration": self.supports_auto_duration,
            "supports_audio": self.supports_audio,
            "max_reference_images": self.max_reference_images,
            "default_resolution": self.default_resolution,
            "default_aspect_ratio": self.default_aspect_ratio,
            "default_output_format": self.default_output_format,
            "default_generate_audio": self.default_generate_audio,
        }


@dataclass(frozen=True)
class VideoGenerationSelection:
    resolution: str
    aspect_ratio: str
    duration: int
    output_format: str
    generate_audio: bool


CAPABILITIES: dict[VideoGenerationModelTypeEnum, VideoModelCapabilities] = {
    VideoGenerationModelTypeEnum.seedance_2: VideoModelCapabilities(
        resolutions=("480p", "720p", "1080p", "4k"),
        aspect_ratios=COMMON_RATIOS,
        aspect_ratios_by_mode={mode: COMMON_RATIOS for mode in GENERATION_MODES},
        output_formats=("mp4",),
        generation_modes=GENERATION_MODES,
        duration_min=4,
        duration_max=15,
        supports_auto_duration=True,
        supports_audio=True,
        max_reference_images=9,
    ),
    VideoGenerationModelTypeEnum.seedance_2_fast: VideoModelCapabilities(
        resolutions=("480p", "720p"),
        aspect_ratios=COMMON_RATIOS,
        aspect_ratios_by_mode={mode: COMMON_RATIOS for mode in GENERATION_MODES},
        output_formats=("mp4",),
        generation_modes=GENERATION_MODES,
        duration_min=4,
        duration_max=15,
        supports_auto_duration=True,
        supports_audio=True,
        max_reference_images=9,
    ),
    VideoGenerationModelTypeEnum.seedance_2_mini: VideoModelCapabilities(
        resolutions=("480p", "720p"),
        aspect_ratios=COMMON_RATIOS,
        aspect_ratios_by_mode={mode: COMMON_RATIOS for mode in GENERATION_MODES},
        output_formats=("mp4",),
        generation_modes=GENERATION_MODES,
        duration_min=4,
        duration_max=15,
        supports_auto_duration=True,
        supports_audio=True,
        max_reference_images=9,
    ),
    VideoGenerationModelTypeEnum.seedance_2_5: VideoModelCapabilities(
        resolutions=("480p", "720p"),
        aspect_ratios=COMMON_RATIOS,
        aspect_ratios_by_mode={
            "reference": COMMON_RATIOS,
            "keyframes": ("adaptive",),
        },
        output_formats=("mp4", "mov"),
        generation_modes=GENERATION_MODES,
        duration_min=4,
        duration_max=30,
        supports_auto_duration=True,
        supports_audio=True,
        max_reference_images=30,
    ),
}


def capabilities_for(model_type: str | VideoGenerationModelTypeEnum | None) -> VideoModelCapabilities:
    try:
        return CAPABILITIES[VideoGenerationModelTypeEnum(model_type)]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="该视频配置未选择受支持的 Seedance 模型类型") from exc


def validate_protocol(model_type: str | VideoGenerationModelTypeEnum, protocol: str) -> None:
    VideoGenerationModelTypeEnum(model_type)
    if protocol != ImageApiProtocol.volcengine_ark.value:
        raise HTTPException(status_code=400, detail="Seedance 视频模型仅支持火山方舟接口协议")


def validate_selection(
    model_type: str | VideoGenerationModelTypeEnum,
    *,
    generation_mode: str,
    resolution: object,
    aspect_ratio: object,
    duration: object,
    output_format: object,
    generate_audio: object,
) -> VideoGenerationSelection:
    normalized = VideoGenerationModelTypeEnum(model_type)
    capabilities = CAPABILITIES[normalized]
    selected_resolution = str(resolution or capabilities.default_resolution).lower()
    selected_ratio = str(aspect_ratio or capabilities.default_aspect_ratio)
    selected_format = str(output_format or capabilities.default_output_format).lower()
    selected_audio = capabilities.default_generate_audio if generate_audio is None else bool(generate_audio)
    try:
        selected_duration = int(duration)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="视频时长无效") from exc

    if generation_mode not in capabilities.generation_modes:
        raise HTTPException(status_code=400, detail="所选生成方式不受当前视频模型支持")
    if selected_resolution not in capabilities.resolutions:
        raise HTTPException(status_code=400, detail="所选分辨率不受当前视频模型支持")
    mode_aspect_ratios = capabilities.aspect_ratios_by_mode.get(
        generation_mode,
        capabilities.aspect_ratios,
    )
    if selected_ratio not in mode_aspect_ratios:
        raise HTTPException(status_code=400, detail="所选比例不受当前视频模型支持")
    if selected_format not in capabilities.output_formats:
        raise HTTPException(status_code=400, detail="所选视频格式不受当前视频模型支持")
    if selected_duration != -1 and not capabilities.duration_min <= selected_duration <= capabilities.duration_max:
        raise HTTPException(
            status_code=400,
            detail=f"当前视频模型仅支持 {capabilities.duration_min}-{capabilities.duration_max} 秒",
        )
    if selected_duration == -1 and not capabilities.supports_auto_duration:
        raise HTTPException(status_code=400, detail="当前视频模型不支持自动时长")
    if selected_audio and not capabilities.supports_audio:
        raise HTTPException(status_code=400, detail="当前视频模型不支持生成同步音频")
    return VideoGenerationSelection(
        resolution=selected_resolution,
        aspect_ratio=selected_ratio,
        duration=selected_duration,
        output_format=selected_format,
        generate_audio=selected_audio,
    )
