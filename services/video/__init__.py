"""视频生成器工厂。"""

from __future__ import annotations

from models.config import AiModelConfig
from services.video.base import BaseVideoGenerator
from services.video.seedance import SeedanceGenerator
from services.video.sora import SoraGenerator
from services.video.veo import VeoGenerator
from services.video.vidu import ViduGenerator
from utils.enums import VideoModelTypeEnum

_GENERATORS: dict[int, type[BaseVideoGenerator]] = {
    VideoModelTypeEnum.viduq2.value: ViduGenerator,
    VideoModelTypeEnum.sora2.value: SoraGenerator,
    VideoModelTypeEnum.seedance.value: SeedanceGenerator,
    VideoModelTypeEnum.veo3.value: VeoGenerator,
}


def get_generator(model_type: int, config: AiModelConfig) -> BaseVideoGenerator:
    """根据 model_type 获取对应的视频生成器实例。"""
    cls = _GENERATORS.get(model_type)
    if cls is None:
        raise ValueError(f"不支持的视频模型类型: {model_type}")
    return cls(config)
