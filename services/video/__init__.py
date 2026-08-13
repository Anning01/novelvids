"""视频生成器工厂。"""

from __future__ import annotations

from models.config import AiModelConfig
from services.video.base import BaseVideoGenerator
from services.video.seedance import SeedanceGenerator
from services.video.capabilities import capabilities_for

def get_generator(config: AiModelConfig) -> BaseVideoGenerator:
    """根据后台配置创建视频生成器；当前仅开放 Seedance 系列。"""
    capabilities_for(config.video_model_type)
    return SeedanceGenerator(config)
