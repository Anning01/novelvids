import pytest
from httpx import AsyncClient
from models.config import AiModelConfig
from services.video.capabilities import capabilities_for
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_api_general_config_defaults_to_english(client: AsyncClient):
    response = await client.get("/api/config/general")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["prompt_language"] == "en"


@pytest.mark.asyncio
async def test_api_update_general_prompt_language(client: AsyncClient):
    response = await client.put(
        "/api/config/general",
        json={"prompt_language": "zh"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["prompt_language"] == "zh"

    persisted = await client.get("/api/config/general")
    assert persisted.json()["data"]["prompt_language"] == "zh"


@pytest.mark.asyncio
async def test_api_rejects_invalid_prompt_language(client: AsyncClient):
    response = await client.put(
        "/api/config/general",
        json={"prompt_language": "ja"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 422


@pytest.mark.asyncio
async def test_api_create_config(client: AsyncClient):
    """创建模型配置。"""
    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "deepseek-v3",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-test-key",
        "model": "deepseek-chat",
        "supports_json_output": True,
        "max_context_characters": 120000,
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "deepseek-v3"
    assert data["is_active"] is False
    assert data["concurrency"] == 1
    assert data["supports_json_output"] is True
    assert data["api_protocol"] == "openai_compatible"
    assert data["max_context_characters"] == 120000

    invalid = await client.post(
        "/api/config",
        json={**payload, "name": "invalid-context", "max_context_characters": 0},
    )
    assert invalid.json()["code"] == 422


@pytest.mark.asyncio
async def test_api_accepts_configured_image_protocol(client: AsyncClient):
    response = await client.post(
        "/api/config",
        json={
            "task_type": AiTaskTypeEnum.reference_image.value,
            "name": "seedream",
            "base_url": "https://ark.example.com/api/v3",
            "api_key": "ark-key",
            "model": "configured-seedream-model",
            "api_protocol": "volcengine_ark",
            "image_model_type": "seedream_5_lite",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["api_protocol"] == "volcengine_ark"


@pytest.mark.asyncio
async def test_api_rejects_unknown_image_protocol(client: AsyncClient):
    response = await client.post(
        "/api/config",
        json={
            "task_type": AiTaskTypeEnum.reference_image.value,
            "name": "unknown-image-api",
            "base_url": "https://image.example.com/v1",
            "api_key": "key",
            "model": "model",
            "api_protocol": "provider-name-guess",
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == 422


@pytest.mark.asyncio
async def test_api_lists_only_active_supported_image_models_with_capabilities(client: AsyncClient):
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        task_types=[AiTaskTypeEnum.reference_image.value],
        name="seedream-pro-active",
        base_url="https://ark.example.com/api/v3",
        api_key="secret",
        model="configured-pro-endpoint",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        is_active=True,
        concurrency=3,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="legacy-unsupported",
        base_url="https://legacy.example.com/v1",
        api_key="legacy-secret",
        model="legacy-model",
        is_active=True,
    )
    response = await client.get("/api/config/image-generation/models")
    assert response.status_code == 200
    assert response.json()["data"] == [{
        "config_id": active.id,
        "name": "seedream-pro-active",
        "model": "configured-pro-endpoint",
        "model_type": "seedream_5_pro",
        "concurrency": 3,
        "pricing": None,
        "capabilities": {
            "clarities": ["1K", "1.5K", "2K"],
            "aspect_ratios": ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"],
            "output_formats": ["png", "jpeg"],
            "generation_counts": [1],
            "default_clarity": "1.5K",
            "default_aspect_ratio": "16:9",
            "default_output_format": "png",
            "default_generation_count": 1,
        },
    }]


@pytest.mark.asyncio
async def test_api_lists_only_active_configured_video_models_with_capabilities(client: AsyncClient):
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        task_types=[AiTaskTypeEnum.video.value],
        name="seedance-2.5-active",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="secret",
        model="configured-seedance-2.5-endpoint",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2_5",
        is_active=True,
        concurrency=2,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="inactive-seedance",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="secret",
        model="inactive-endpoint",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=False,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="legacy-unsupported-video",
        base_url="https://legacy.example.com/v1",
        api_key="secret",
        model="legacy-endpoint",
        is_active=True,
    )

    response = await client.get("/api/config/video-generation/models")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == [{
        "config_id": active.id,
        "name": "seedance-2.5-active",
        "model": "configured-seedance-2.5-endpoint",
        "model_type": "seedance_2_5",
        "concurrency": 2,
        "pricing": None,
        "capabilities": capabilities_for("seedance_2_5").public_dict(),
    }]


@pytest.mark.asyncio
async def test_api_get_config_list(client: AsyncClient):
    """获取配置列表。"""
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="config-a",
        base_url="https://a.com",
        api_key="key-a",
        model="model-a",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="config-b",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
    )

    response = await client.get("/api/config")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pagination"]["total"] >= 2


@pytest.mark.asyncio
async def test_api_get_config_detail(client: AsyncClient):
    """获取配置详情。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="detail-config",
        base_url="https://api.example.com",
        api_key="sk-detail",
        model="gpt-4o",
    )

    response = await client.get(f"/api/config/{config.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == config.id
    assert data["name"] == "detail-config"


@pytest.mark.asyncio
async def test_api_update_config(client: AsyncClient):
    """全量更新配置。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="old-name",
        base_url="https://old.com",
        api_key="old-key",
        model="old-model",
    )

    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "new-name",
        "base_url": "https://new.com",
        "api_key": "new-key",
        "model": "new-model",
    }
    response = await client.put(f"/api/config/{config.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "new-name"
    assert data["base_url"] == "https://new.com"


@pytest.mark.asyncio
async def test_api_patch_config(client: AsyncClient):
    """局部更新配置。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="patch-config",
        base_url="https://api.example.com",
        api_key="sk-patch",
        model="gpt-4o",
    )

    response = await client.patch(
        f"/api/config/{config.id}",
        json={"model": "gpt-4o-mini"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["model"] == "gpt-4o-mini"
    assert data["name"] == "patch-config"  # 未改动


@pytest.mark.asyncio
async def test_api_delete_config(client: AsyncClient):
    """删除配置。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="delete-config",
        base_url="https://api.example.com",
        api_key="sk-del",
        model="gpt-4o",
    )

    response = await client.delete(f"/api/config/{config.id}")
    assert response.status_code == 200, response.text

    exists = await AiModelConfig.filter(id=config.id).exists()
    assert not exists


@pytest.mark.asyncio
async def test_api_activate_config(client: AsyncClient):
    """启用配置后，同 task_type 的多个模型可以同时运行。"""
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="config-1",
        base_url="https://1.com",
        api_key="key-1",
        model="model-1",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="config-2",
        base_url="https://2.com",
        api_key="key-2",
        model="model-2",
    )

    # 启用 c2
    response = await client.post(f"/api/config/{c2.id}/activate")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    # 验证 c1 继续运行
    await c1.refresh_from_db()
    assert c1.is_active is True


@pytest.mark.asyncio
async def test_api_create_config_with_active(client: AsyncClient):
    """创建时传 is_active=True，同类型旧配置继续运行。"""
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="existing-active",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )

    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "new-active",
        "base_url": "https://new.com",
        "api_key": "key-new",
        "model": "model-new",
        "is_active": True,
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    # 旧配置继续运行
    await c1.refresh_from_db()
    assert c1.is_active is True


@pytest.mark.asyncio
async def test_api_update_config_with_active(client: AsyncClient):
    """全量更新时传 is_active=True，不影响同类型旧配置。"""
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-before-update",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-update",
        base_url="https://u.com",
        api_key="key-u",
        model="model-u",
    )

    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "to-update",
        "base_url": "https://u.com",
        "api_key": "key-u",
        "model": "model-u",
        "is_active": True,
    }
    response = await client.put(f"/api/config/{c2.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    # 旧配置继续运行
    await c1.refresh_from_db()
    assert c1.is_active is True


@pytest.mark.asyncio
async def test_api_patch_config_with_active(client: AsyncClient):
    """局部更新时传 is_active=True，不影响同类型旧配置。"""
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-before-patch",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-patch",
        base_url="https://p.com",
        api_key="key-p",
        model="model-p",
    )

    response = await client.patch(
        f"/api/config/{c2.id}",
        json={"is_active": True},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    # 旧配置继续运行
    await c1.refresh_from_db()
    assert c1.is_active is True


@pytest.mark.asyncio
async def test_api_activate_does_not_affect_other_task_types(client: AsyncClient):
    """启用配置不影响其他 task_type 的配置。"""
    extraction = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="extraction-active",
        base_url="https://e.com",
        api_key="key-e",
        model="model-e",
        is_active=True,
    )
    video = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-config",
        base_url="https://v.com",
        api_key="key-v",
        model="model-v",
        is_active=True,
    )

    # 创建并启用新的 extraction 配置
    new_ext = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="extraction-new",
        base_url="https://e2.com",
        api_key="key-e2",
        model="model-e2",
    )
    await client.post(f"/api/config/{new_ext.id}/activate")

    # video 配置不受影响
    await video.refresh_from_db()
    assert video.is_active is True

    # 旧的 extraction 继续运行
    await extraction.refresh_from_db()
    assert extraction.is_active is True


@pytest.mark.asyncio
async def test_api_deactivate_only_stops_target_config(client: AsyncClient):
    first = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image-running-first",
        base_url="https://first.example.com",
        api_key="key-first",
        model="model-first",
        is_active=True,
    )
    second = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image-running-second",
        base_url="https://second.example.com",
        api_key="key-second",
        model="model-second",
        is_active=True,
    )

    response = await client.post(f"/api/config/{second.id}/deactivate")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["is_active"] is False
    await first.refresh_from_db()
    assert first.is_active is True


@pytest.mark.asyncio
async def test_api_获取所有枚举(client: AsyncClient):
    """GET /api/config/enums/all 返回所有枚举。"""
    response = await client.get("/api/config/enums/all")
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    # 验证所有枚举 key 都存在
    expected_keys = {
        "task_status", "asset_type", "image_source",
        "workflow_status", "ai_task_type", "video_model_type",
        "image_model_type",
    }
    assert set(data.keys()) == expected_keys

    # 验证每项结构: [{value, label, name}]
    for key in expected_keys:
        items = data[key]
        assert len(items) > 0, f"{key} 不应为空"
        first = items[0]
        assert "value" in first
        assert "label" in first
        assert "name" in first

    # 抽查具体值
    video_types = {item["name"]: item for item in data["video_model_type"]}
    assert set(video_types) == {
        "seedance_2",
        "seedance_2_fast",
        "seedance_2_mini",
        "seedance_2_5",
        "minimax_h3",
        "wan_3",
    }
    assert video_types["seedance_2"]["value"] == "seedance_2"
    assert video_types["seedance_2"]["label"] == "Doubao Seedance 2.0"
    print(f"    枚举接口: keys={list(data.keys())}, video_model_type count={len(data['video_model_type'])}")
