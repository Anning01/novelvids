import pytest
from httpx import AsyncClient
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_api_create_config(client: AsyncClient):
    """创建模型配置。"""
    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "deepseek-v3",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-test-key",
        "model": "deepseek-chat",
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "deepseek-v3"
    assert data["is_active"] is False
    assert data["concurrency"] == 1


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
    """启用配置 - 同 task_type 只能有一个 active。"""
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

    # 验证 c1 被自动禁用
    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_create_config_with_active(client: AsyncClient):
    """创建时传 is_active=True，同类型旧的自动禁用。"""
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

    # 旧配置应被禁用
    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_update_config_with_active(client: AsyncClient):
    """全量更新时传 is_active=True，同类型旧的自动禁用。"""
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

    # 旧配置应被禁用
    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_patch_config_with_active(client: AsyncClient):
    """局部更新时传 is_active=True，同类型旧的自动禁用。"""
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

    # 旧配置应被禁用
    await c1.refresh_from_db()
    assert c1.is_active is False


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

    # 旧的 extraction 被禁用
    await extraction.refresh_from_db()
    assert extraction.is_active is False
