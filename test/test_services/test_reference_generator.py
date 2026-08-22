from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.reference.generator import generate_for_sora_consistency


@pytest.mark.asyncio
async def test_generation_count_runs_supported_single_image_requests_and_collects_all_results():
    generated = AsyncMock(side_effect=[
        [SimpleNamespace(url="https://cdn.example.com/1.png")],
        [SimpleNamespace(url="https://cdn.example.com/2.png")],
        [SimpleNamespace(url="https://cdn.example.com/3.png")],
        [SimpleNamespace(url="https://cdn.example.com/4.png")],
    ])
    stored_prompt = "用户保存的山间古寺场景 Prompt"
    with patch("services.reference.generator.generate_images", new=generated):
        result = await generate_for_sora_consistency(
            {
                "type": "scene",
                "base_traits": stored_prompt,
                "description": "不应发送的剧情描述",
            },
            base_url="https://image.example.com/v1",
            api_key="secret",
            model="configured-model",
            count=4,
            output_format="jpeg",
        )

    assert [image.url for image in result] == [
        "https://cdn.example.com/1.png",
        "https://cdn.example.com/2.png",
        "https://cdn.example.com/3.png",
        "https://cdn.example.com/4.png",
    ]
    assert generated.await_count == 4
    assert all(
        call.kwargs["prompt"] == stored_prompt
        for call in generated.await_args_list
    )
    assert all(call.kwargs["count"] == 1 for call in generated.await_args_list)
    assert all(call.kwargs["output_format"] == "jpeg" for call in generated.await_args_list)


@pytest.mark.asyncio
async def test_generation_forwards_image_inputs_to_the_configured_protocol():
    generated = AsyncMock(return_value=[SimpleNamespace(url="https://cdn.example.com/result.png")])
    references = ["data:image/png;base64,aW1hZ2U="]

    with patch("services.reference.generator.generate_images", new=generated):
        await generate_for_sora_consistency(
            {"type": "person", "base_traits": "保持参考人物一致并生成角色设定图"},
            base_url="https://ark.example.com/api/v3",
            api_key="secret",
            api_protocol="volcengine_ark",
            model="doubao-seedream-5-0-lite",
            reference_images=references,
        )

    assert generated.await_args.kwargs["extra_body"] == {"image": references}
