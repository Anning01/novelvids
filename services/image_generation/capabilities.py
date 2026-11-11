from __future__ import annotations

from utils.messages import localized_message

from dataclasses import dataclass, replace

from fastapi import HTTPException

from utils.enums import ImageModelTypeEnum
from utils.image_protocol import ImageApiProtocol


COMMON_SEEDREAM_RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9")


@dataclass(frozen=True)
class ImageModelCapabilities:
    clarities: tuple[str, ...]
    aspect_ratios: tuple[str, ...]
    output_formats: tuple[str, ...]
    generation_counts: tuple[int, ...]
    default_clarity: str
    sizes: dict[str, tuple[str, ...]]
    qualities: dict[str, str] | None = None
    legacy_clarities: tuple[str, ...] = ()
    frame_counts: tuple[int, ...] = ()
    default_frame_count: int = 9
    frame_duration_ms_min: int = 20
    frame_duration_ms_max: int = 655350
    frame_duration_ms_step: int = 10
    default_frame_duration_ms: int = 200
    clarities_by_format: dict[str, tuple[str, ...]] | None = None
    qualities_by_format: dict[str, dict[str, str]] | None = None
    default_aspect_ratio: str = "16:9"
    default_output_format: str = "png"
    default_generation_count: int = 1

    def public_dict(self) -> dict:
        return {
            "clarities": list(self.clarities),
            "aspect_ratios": list(self.aspect_ratios),
            "output_formats": list(self.output_formats),
            "generation_counts": list(self.generation_counts),
            "default_clarity": self.default_clarity,
            "default_aspect_ratio": self.default_aspect_ratio,
            "default_output_format": self.default_output_format,
            "default_generation_count": self.default_generation_count,
            "frame_counts": list(self.frame_counts),
            "default_frame_count": self.default_frame_count,
            "frame_duration_ms_min": self.frame_duration_ms_min,
            "frame_duration_ms_max": self.frame_duration_ms_max,
            "frame_duration_ms_step": self.frame_duration_ms_step,
            "default_frame_duration_ms": self.default_frame_duration_ms,
            "clarities_by_format": {key: list(values) for key, values in (self.clarities_by_format or {}).items()},
        }


@dataclass(frozen=True)
class ImageGenerationSelection:
    clarity: str
    aspect_ratio: str
    output_format: str
    generation_count: int
    provider_size: str
    provider_quality: str | None = None
    frame_count: int | None = None
    frame_duration_ms: int | None = None


_STANDARD_IMAGE_SIZES = {
    "1K": ("1024x1024", "1152x864", "864x1152", "1424x800", "800x1424", "1248x832", "832x1248", "1568x672"),
    "1.5K": ("1536x1536", "1792x1344", "1344x1792", "2048x1152", "1152x2048", "1872x1248", "1248x1872", "2352x1008"),
    "2K": ("2048x2048", "2368x1776", "1776x2368", "2816x1584", "1584x2816", "2496x1664", "1664x2496", "3136x1344"),
}

_SEEDREAM_LITE_SIZES = {
    "2K": ("2048x2048", "2304x1728", "1728x2304", "2848x1600", "1600x2848", "2496x1664", "1664x2496", "3136x1344"),
    "3K": ("3072x3072", "3456x2592", "2592x3456", "4096x2304", "2304x4096", "3744x2496", "2496x3744", "4704x2016"),
    "4K": ("4096x4096", "4704x3520", "3520x4704", "5504x3040", "3040x5504", "4992x3328", "3328x4992", "6240x2656"),
}

GPT_IMAGE_K_MODELS = (
    ImageModelTypeEnum.gpt_image_2_5,
    ImageModelTypeEnum.gpt_image_2_6,
    ImageModelTypeEnum.gpt_image_2_6_sunburst,
    ImageModelTypeEnum.gpt_image_2_6_flare,
)
GPT_IMAGE_MODELS = (ImageModelTypeEnum.gpt_image_2, *GPT_IMAGE_K_MODELS)
GIF_IMAGE_MODELS = (
    ImageModelTypeEnum.gpt_image_2_6,
    ImageModelTypeEnum.gpt_image_2_6_sunburst,
    ImageModelTypeEnum.gpt_image_2_6_flare,
)
_GPT_IMAGE_CAPABILITIES = ImageModelCapabilities(
    clarities=("1K", "2K", "4K"),
    aspect_ratios=COMMON_SEEDREAM_RATIOS,
    output_formats=("png", "jpeg", "webp"),
    generation_counts=(1,),
    default_clarity="1K",
    default_aspect_ratio="1:1",
    sizes={"1K": _STANDARD_IMAGE_SIZES["1K"], "2K": _STANDARD_IMAGE_SIZES["2K"], "4K": _SEEDREAM_LITE_SIZES["4K"]},
    qualities={tier: "high" for tier in ("1K", "2K", "4K")},
    legacy_clarities=("low", "medium", "high"),
)

CAPABILITIES: dict[ImageModelTypeEnum, ImageModelCapabilities] = {
    ImageModelTypeEnum.seedream_5_pro: ImageModelCapabilities(
        clarities=("1K", "1.5K", "2K"),
        aspect_ratios=COMMON_SEEDREAM_RATIOS,
        output_formats=("png", "jpeg"),
        generation_counts=(1,),
        default_clarity="1.5K",
        sizes=_STANDARD_IMAGE_SIZES,
    ),
    ImageModelTypeEnum.seedream_5_flash: ImageModelCapabilities(
        clarities=("1K", "1.5K", "2K"),
        aspect_ratios=COMMON_SEEDREAM_RATIOS,
        output_formats=("png", "jpeg"),
        generation_counts=(1,),
        default_clarity="2K",
        sizes=_STANDARD_IMAGE_SIZES,
    ),
    ImageModelTypeEnum.seedream_5_lite: ImageModelCapabilities(
        clarities=("2K", "3K", "4K"),
        aspect_ratios=COMMON_SEEDREAM_RATIOS,
        output_formats=("png", "jpeg"),
        generation_counts=(1,),
        default_clarity="2K",
        sizes=_SEEDREAM_LITE_SIZES,
    ),
    **{model_type: _GPT_IMAGE_CAPABILITIES for model_type in GPT_IMAGE_MODELS},
    **{model_type: replace(_GPT_IMAGE_CAPABILITIES,
        output_formats=("png", "jpeg", "webp", "gif"), frame_counts=tuple(range(2, 17)),
        clarities_by_format={"gif": ("1K",)}, qualities_by_format={"gif": {"1K": "1k"}})
       for model_type in GIF_IMAGE_MODELS},
}

PROTOCOLS: dict[ImageModelTypeEnum, tuple[ImageApiProtocol, ...]] = {
    ImageModelTypeEnum.seedream_5_pro: (
        ImageApiProtocol.volcengine_ark,
        ImageApiProtocol.openrouter_compatible,
    ),
    ImageModelTypeEnum.seedream_5_flash: (ImageApiProtocol.volcengine_ark,),
    ImageModelTypeEnum.seedream_5_lite: (
        ImageApiProtocol.volcengine_ark,
        ImageApiProtocol.openrouter_compatible,
    ),
    ImageModelTypeEnum.gpt_image_2: (
        ImageApiProtocol.openai_compatible,
        ImageApiProtocol.openrouter_compatible,
    ),
    **{model_type: (ImageApiProtocol.openai_compatible,) for model_type in GPT_IMAGE_K_MODELS},
}


PROTOCOLS = {kind: (*protocols, ImageApiProtocol.novelvids) for kind, protocols in PROTOCOLS.items()}

def capabilities_for(model_type: str | ImageModelTypeEnum | None) -> ImageModelCapabilities:
    try:
        return CAPABILITIES[ImageModelTypeEnum(model_type)]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=localized_message('该生图配置未选择受支持的模型类型')) from exc


def validate_protocol(model_type: str | ImageModelTypeEnum, protocol: str) -> None:
    normalized = ImageModelTypeEnum(model_type)
    allowed = PROTOCOLS[normalized]
    if protocol not in {item.value for item in allowed}:
        raise HTTPException(
            status_code=400,
            detail=localized_message('{p0} 不支持当前接口协议', p0=f'{normalized.nickname}'),
        )


def validate_selection(
    model_type: str | ImageModelTypeEnum,
    *,
    clarity: object,
    aspect_ratio: object,
    output_format: object,
    generation_count: object,
    frame_count: object = None,
    frame_duration_ms: object = None,
) -> ImageGenerationSelection:
    normalized = ImageModelTypeEnum(model_type)
    capabilities = CAPABILITIES[normalized]
    selected_clarity = str(clarity or capabilities.default_clarity)
    if selected_clarity in capabilities.legacy_clarities:
        selected_clarity = capabilities.default_clarity
    selected_ratio = str(aspect_ratio or capabilities.default_aspect_ratio)
    selected_format = str(output_format or capabilities.default_output_format).lower()
    try:
        selected_count = int(generation_count or capabilities.default_generation_count)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=localized_message('生成数量无效')) from exc

    checks = (
        (selected_clarity in (capabilities.clarities_by_format or {}).get(selected_format, capabilities.clarities), "所选清晰度不受当前模型支持"),
        (selected_ratio in capabilities.aspect_ratios, "所选比例不受当前模型支持"),
        (selected_format in capabilities.output_formats, "所选图片格式不受当前模型支持"),
        (selected_count in capabilities.generation_counts, "所选生成数量不受当前模型支持"),
    )
    for valid, detail in checks:
        if not valid:
            raise HTTPException(status_code=400, detail=detail)

    provider_size = capabilities.sizes[selected_clarity][capabilities.aspect_ratios.index(selected_ratio)]
    qualities = (capabilities.qualities_by_format or {}).get(selected_format, capabilities.qualities)
    provider_quality = qualities.get(selected_clarity) if qualities else None
    selected_frames = selected_interval = None
    if selected_format == "gif":
        selected_frames = capabilities.default_frame_count if frame_count is None else frame_count
        selected_interval = capabilities.default_frame_duration_ms if frame_duration_ms is None else frame_duration_ms
        if isinstance(selected_frames, bool) or not isinstance(selected_frames, int) or selected_frames not in capabilities.frame_counts:
            raise HTTPException(status_code=400, detail=localized_message('所选动图帧数不受当前模型支持'))
        if isinstance(selected_interval, bool) or not isinstance(selected_interval, int) or not capabilities.frame_duration_ms_min <= selected_interval <= capabilities.frame_duration_ms_max:
            raise HTTPException(status_code=400, detail=localized_message('所选动图帧间隔不受当前模型支持'))
        step = capabilities.frame_duration_ms_step
        selected_interval = min(capabilities.frame_duration_ms_max, ((selected_interval + step // 2) // step) * step)

    return ImageGenerationSelection(
        clarity=selected_clarity,
        aspect_ratio=selected_ratio,
        output_format=selected_format,
        generation_count=selected_count,
        provider_size=provider_size,
        provider_quality=provider_quality,
        frame_count=selected_frames,
        frame_duration_ms=selected_interval,
    )
