"""视频生成器公开入口。"""

from __future__ import annotations

from models.config import AiModelConfig
from services.video.base import BaseVideoGenerator
from services.video.factory import video_generator_factory
from utils.enums import VideoModelTypeEnum

def get_generator(config: AiModelConfig) -> BaseVideoGenerator:
    """根据后台 video_model_type 创建对应供应商生成器。"""
    return video_generator_factory.create(config)


def get_record_model_type(config: AiModelConfig) -> VideoModelTypeEnum:
    """返回视频记录使用的兼容供应商枚举。"""
    return video_generator_factory.record_model_type(config.video_model_type)
