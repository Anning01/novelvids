"""配置驱动的视频生成器注册工厂。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException

from models.config import AiModelConfig
from services.video.base import BaseVideoGenerator
from services.video.capabilities import capabilities_for
from services.video.minimax import MiniMaxH3Generator
from services.video.seedance import SeedanceGenerator
from services.video.wan import Wan3Generator
from utils.enums import VideoGenerationModelTypeEnum, VideoModelTypeEnum


GeneratorBuilder = Callable[[AiModelConfig], BaseVideoGenerator]


@dataclass(frozen=True)
class VideoGeneratorAdapterSpec:
    builder: GeneratorBuilder
    record_model_type: VideoModelTypeEnum


class VideoGeneratorFactory:
    """由 video_model_type 选择供应商适配器，不依赖模型名称猜测。"""

    def __init__(
        self,
        registry: dict[VideoGenerationModelTypeEnum, VideoGeneratorAdapterSpec],
    ):
        self._registry = dict(registry)

    @property
    def registered_model_types(self) -> frozenset[VideoGenerationModelTypeEnum]:
        """返回已经可由 Factory 创建生成器的模型类型。"""
        return frozenset(self._registry)

    def validate_model_type(
        self,
        model_type: str | VideoGenerationModelTypeEnum | None,
    ) -> None:
        """确保后台可选模型已注册具体请求适配器。"""
        try:
            normalized = VideoGenerationModelTypeEnum(model_type)
            self._registry[normalized]
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="该视频模型尚未配置请求适配器") from exc

    def create(self, config: AiModelConfig) -> BaseVideoGenerator:
        capabilities_for(config.video_model_type)
        self.validate_model_type(config.video_model_type)
        model_type = VideoGenerationModelTypeEnum(config.video_model_type)
        spec = self._registry[model_type]
        return spec.builder(config)

    def record_model_type(
        self,
        model_type: str | VideoGenerationModelTypeEnum,
    ) -> VideoModelTypeEnum:
        self.validate_model_type(model_type)
        return self._registry[VideoGenerationModelTypeEnum(model_type)].record_model_type


video_generator_factory = VideoGeneratorFactory({
    VideoGenerationModelTypeEnum.seedance_2: VideoGeneratorAdapterSpec(
        SeedanceGenerator, VideoModelTypeEnum.seedance
    ),
    VideoGenerationModelTypeEnum.seedance_2_fast: VideoGeneratorAdapterSpec(
        SeedanceGenerator, VideoModelTypeEnum.seedance
    ),
    VideoGenerationModelTypeEnum.seedance_2_mini: VideoGeneratorAdapterSpec(
        SeedanceGenerator, VideoModelTypeEnum.seedance
    ),
    VideoGenerationModelTypeEnum.seedance_2_5: VideoGeneratorAdapterSpec(
        SeedanceGenerator, VideoModelTypeEnum.seedance
    ),
    VideoGenerationModelTypeEnum.minimax_h3: VideoGeneratorAdapterSpec(
        MiniMaxH3Generator, VideoModelTypeEnum.minimax
    ),
    VideoGenerationModelTypeEnum.wan_3: VideoGeneratorAdapterSpec(
        Wan3Generator, VideoModelTypeEnum.wan
    ),
})
