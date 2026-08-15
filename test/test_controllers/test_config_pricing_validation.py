import pytest
from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from schemas.config import AiModelConfigCreate
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_文本模型接受合法pricing():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="text-priced",
        base_url="https://api.example.com",
        api_key="sk",
        model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    ))
    assert config.pricing["type"] == "text"


@pytest.mark.asyncio
async def test_文本模型缺少价格字段被拒绝():
    with pytest.raises(HTTPException, match="output_price_per_1m"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.extraction.value,
            name="bad-text",
            base_url="https://api.example.com",
            api_key="sk",
            model="m",
            pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0},
        ))


@pytest.mark.asyncio
async def test_生图模型接受合法档位pricing():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image-priced",
        base_url="https://ark.example.com/api/v3",
        api_key="sk",
        model="m",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.10, "2K": 0.20}},
    ))
    assert config.pricing["prices"]["1K"] == 0.10


@pytest.mark.asyncio
async def test_生图模型非法档位被拒绝():
    with pytest.raises(HTTPException, match="不支持的清晰度档位"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.reference_image.value,
            name="bad-image",
            base_url="https://ark.example.com/api/v3",
            api_key="sk",
            model="m",
            api_protocol="volcengine_ark",
            image_model_type="seedream_5_pro",
            pricing={"type": "image", "currency": "CNY", "prices": {"9K": 0.10}},
        ))


@pytest.mark.asyncio
async def test_视频模型非法分辨率被拒绝():
    with pytest.raises(HTTPException, match="不支持的清晰度档位|分辨率档位"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="bad-video",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="sk",
            model="m",
            api_protocol="volcengine_ark",
            video_model_type="seedance_2",
            pricing={"type": "video", "currency": "CNY", "prices": {"8k": 1.0}},
        ))
