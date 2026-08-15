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


@pytest.mark.asyncio
async def test_生图模型接受输入图费用():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image-input-fee",
        base_url="https://ark.example.com/api/v3",
        api_key="sk",
        model="m",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.30}, "input_image": {"first_free": 1, "price_per_image": 0.02}},
    ))
    assert config.pricing["input_image"]["price_per_image"] == 0.02


@pytest.mark.asyncio
async def test_生图模型非法输入图费用被拒绝():
    with pytest.raises(HTTPException, match="first_free"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.reference_image.value,
            name="bad-image-input",
            base_url="https://ark.example.com/api/v3",
            api_key="sk",
            model="m",
            api_protocol="volcengine_ark",
            image_model_type="seedream_5_pro",
            pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.30}, "input_image": {"first_free": -1, "price_per_image": 0.02}},
        ))


@pytest.mark.asyncio
async def test_视频模型接受参考价表():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="video-ref-price",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="sk",
        model="m",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 1.0}, "video_reference_prices": {"720p": 1.5}},
    ))
    assert config.pricing["video_reference_prices"]["720p"] == 1.5


@pytest.mark.asyncio
async def test_视频模型非法参考价表被拒绝():
    with pytest.raises(HTTPException, match="分辨率档位"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="bad-video-ref",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="sk",
            model="m",
            api_protocol="volcengine_ark",
            video_model_type="seedance_2",
            pricing={"type": "video", "currency": "CNY", "prices": {"720p": 1.0}, "video_reference_prices": {"8k": 1.5}},
        ))


@pytest.mark.asyncio
async def test_接受折扣配置():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="discounted",
        base_url="https://api.example.com",
        api_key="sk",
        model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0, "discount": 0.9, "discount_description": "限时9折"},
    ))
    assert config.pricing["discount"] == 0.9
    assert config.pricing["discount_description"] == "限时9折"


@pytest.mark.asyncio
async def test_非法折扣被拒绝():
    with pytest.raises(HTTPException, match="折扣倍数"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.extraction.value,
            name="bad-discount",
            base_url="https://api.example.com",
            api_key="sk",
            model="m",
            pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0, "discount": 0},
        ))
