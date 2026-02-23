import pytest
from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate, AiModelConfigUpdate, AiModelConfigPatch
from utils.enums import AiTaskTypeEnum


# =====================================================================
# 基础 CRUD
# =====================================================================

@pytest.mark.asyncio
async def test_创建配置_默认不启用():
    """创建配置，默认 is_active=False。"""
    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="test-config",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="gpt-4o",
    )
    config = await ai_model_config_controller.create(obj_in)
    assert config.id is not None
    assert config.is_active is False
    assert config.concurrency == 1


@pytest.mark.asyncio
async def test_创建配置_传入is_active为True():
    """创建时 is_active=True，应正常创建。"""
    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-config",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="gpt-4o",
        is_active=True,
    )
    config = await ai_model_config_controller.create(obj_in)
    assert config.is_active is True


@pytest.mark.asyncio
async def test_创建配置_启用时同类型旧的自动禁用():
    """创建新配置并启用，同类型下原有的应被自动禁用。"""
    old = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="old-active",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )

    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="new-active",
        base_url="https://new.com",
        api_key="key-new",
        model="model-new",
        is_active=True,
    )
    new = await ai_model_config_controller.create(obj_in)
    assert new.is_active is True

    await old.refresh_from_db()
    assert old.is_active is False


@pytest.mark.asyncio
async def test_创建配置_不启用不影响其他():
    """创建时不启用，已有的启用配置不受影响。"""
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="existing-active",
        base_url="https://a.com",
        api_key="key",
        model="model",
        is_active=True,
    )

    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="new-inactive",
        base_url="https://b.com",
        api_key="key2",
        model="model2",
    )
    await ai_model_config_controller.create(obj_in)

    await active.refresh_from_db()
    assert active.is_active is True


# =====================================================================
# 全量更新
# =====================================================================

@pytest.mark.asyncio
async def test_全量更新配置():
    """全量更新配置字段。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="before-update",
        base_url="https://old.com",
        api_key="old-key",
        model="old-model",
    )

    obj_in = AiModelConfigUpdate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="after-update",
        base_url="https://new.com",
        api_key="new-key",
        model="new-model",
    )
    result = await ai_model_config_controller.update(config.id, obj_in)
    assert result.name == "after-update"
    assert result.base_url == "https://new.com"


@pytest.mark.asyncio
async def test_全量更新配置_传入is_active禁用同类型():
    """全量更新时传 is_active=True，同类型下其他应被禁用。"""
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="currently-active",
        base_url="https://a.com",
        api_key="key-a",
        model="model-a",
        is_active=True,
    )
    target = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-update",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
    )

    obj_in = AiModelConfigUpdate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-update",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
        is_active=True,
    )
    result = await ai_model_config_controller.update(target.id, obj_in)
    assert result.is_active is True

    await active.refresh_from_db()
    assert active.is_active is False


# =====================================================================
# 局部更新
# =====================================================================

@pytest.mark.asyncio
async def test_局部更新配置_只改一个字段():
    """局部更新只传 model 字段，其他不变。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="patch-config",
        base_url="https://api.example.com",
        api_key="sk-patch",
        model="gpt-4o",
    )

    obj_in = AiModelConfigPatch(model="gpt-4o-mini")
    result = await ai_model_config_controller.patch(config.id, obj_in)
    assert result.model == "gpt-4o-mini"
    assert result.name == "patch-config"  # 未改动


@pytest.mark.asyncio
async def test_局部更新配置_传入is_active禁用同类型():
    """局部更新传 is_active=True，同类型旧的应被禁用。"""
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-before-patch",
        base_url="https://a.com",
        api_key="key-a",
        model="model-a",
        is_active=True,
    )
    target = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="target-patch",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
    )

    obj_in = AiModelConfigPatch(is_active=True)
    result = await ai_model_config_controller.patch(target.id, obj_in)
    assert result.is_active is True

    await active.refresh_from_db()
    assert active.is_active is False


# =====================================================================
# 删除
# =====================================================================

@pytest.mark.asyncio
async def test_删除配置():
    """删除配置后数据库中不再存在。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-delete",
        base_url="https://d.com",
        api_key="key",
        model="model",
    )

    await ai_model_config_controller.remove(config.id)
    exists = await AiModelConfig.filter(id=config.id).exists()
    assert not exists


@pytest.mark.asyncio
async def test_删除不存在的配置_抛出404():
    """删除不存在的 ID 应抛出 404。"""
    with pytest.raises(Exception):
        await ai_model_config_controller.remove(99999)


# =====================================================================
# 启用
# =====================================================================

@pytest.mark.asyncio
async def test_启用配置():
    """调用 activate 启用指定配置。"""
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-activate",
        base_url="https://act.com",
        api_key="key",
        model="model",
    )
    assert config.is_active is False

    result = await ai_model_config_controller.activate(config.id)
    assert result.is_active is True


@pytest.mark.asyncio
async def test_启用配置_同类型旧的自动禁用():
    """启用新配置时，同 task_type 下其他已启用的应被禁用。"""
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="c1-active",
        base_url="https://1.com",
        api_key="key-1",
        model="model-1",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="c2-inactive",
        base_url="https://2.com",
        api_key="key-2",
        model="model-2",
    )

    await ai_model_config_controller.activate(c2.id)

    await c1.refresh_from_db()
    assert c1.is_active is False

    await c2.refresh_from_db()
    assert c2.is_active is True


@pytest.mark.asyncio
async def test_启用配置_不同类型互不影响():
    """启用 extraction 配置不影响 video 类型。"""
    video = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-active",
        base_url="https://v.com",
        api_key="key-v",
        model="model-v",
        is_active=True,
    )
    ext1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="ext-1",
        base_url="https://e1.com",
        api_key="key-e1",
        model="model-e1",
        is_active=True,
    )
    ext2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="ext-2",
        base_url="https://e2.com",
        api_key="key-e2",
        model="model-e2",
    )

    await ai_model_config_controller.activate(ext2.id)

    await video.refresh_from_db()
    assert video.is_active is True  # video 不受影响

    await ext1.refresh_from_db()
    assert ext1.is_active is False  # 同类型 ext 被禁用


# =====================================================================
# 获取启用配置
# =====================================================================

@pytest.mark.asyncio
async def test_获取启用配置():
    """get_active 返回指定类型下唯一启用的配置。"""
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="the-active-one",
        base_url="https://active.com",
        api_key="key",
        model="model",
        is_active=True,
    )

    result = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.extraction.value
    )
    assert result.name == "the-active-one"
    assert result.is_active is True


@pytest.mark.asyncio
async def test_获取启用配置_无启用时抛出404():
    """没有启用配置时应抛出 HTTPException 404。"""
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="inactive-only",
        base_url="https://i.com",
        api_key="key",
        model="model",
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await ai_model_config_controller.get_active(
            AiTaskTypeEnum.extraction.value
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_多个类型各有启用配置_互不干扰():
    """不同 task_type 各有一个启用配置，互不干扰。"""
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="ext-active",
        base_url="https://e.com",
        api_key="key-e",
        model="model-e",
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-active",
        base_url="https://v.com",
        api_key="key-v",
        model="model-v",
        is_active=True,
    )

    ext = await ai_model_config_controller.get_active(AiTaskTypeEnum.extraction.value)
    assert ext.name == "ext-active"

    vid = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)
    assert vid.name == "video-active"
