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
async def test_单个模型支持多个能力用途():
    """同一配置可同时服务内容提取、分镜生成与项目分析。"""
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[
            AiTaskTypeEnum.extraction.value,
            AiTaskTypeEnum.storyboard.value,
            AiTaskTypeEnum.project_analysis.value,
        ],
        name="multi-purpose-llm",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="deepseek-v4-pro",
        is_active=True,
    ))

    assert config.task_types == [
        AiTaskTypeEnum.extraction.value,
        AiTaskTypeEnum.storyboard.value,
        AiTaskTypeEnum.project_analysis.value,
    ]
    assert await ai_model_config_controller.get_active(AiTaskTypeEnum.extraction.value) == config
    assert await ai_model_config_controller.get_active(AiTaskTypeEnum.storyboard.value) == config
    assert await ai_model_config_controller.get_active(AiTaskTypeEnum.project_analysis.value) == config


@pytest.mark.asyncio
async def test_项目分析优先使用独立能力配置():
    legacy = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="legacy-extraction",
        base_url="https://legacy.example.com",
        api_key="legacy-key",
        model="legacy-model",
        is_active=True,
    )
    dedicated = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.project_analysis.value,
        task_types=[AiTaskTypeEnum.project_analysis.value],
        name="project-analysis",
        base_url="https://analysis.example.com",
        api_key="analysis-key",
        model="analysis-model",
        is_active=True,
    )

    selected = await ai_model_config_controller.get_active_with_legacy_fallback(
        AiTaskTypeEnum.project_analysis.value,
        AiTaskTypeEnum.extraction.value,
    )

    assert selected == dedicated
    assert selected != legacy


@pytest.mark.asyncio
async def test_项目分析兼容旧的提取模型配置():
    legacy = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value],
        name="legacy-project-analysis",
        base_url="https://legacy.example.com",
        api_key="legacy-key",
        model="legacy-model",
        is_active=True,
    )

    selected = await ai_model_config_controller.get_active_with_legacy_fallback(
        AiTaskTypeEnum.project_analysis.value,
        AiTaskTypeEnum.extraction.value,
    )

    assert selected == legacy


@pytest.mark.asyncio
async def test_多能力配置不会停用能力重叠的旧配置():
    """启用多用途模型时，能力重叠的配置可以继续运行。"""
    old_storyboard = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.storyboard.value,
        task_types=[AiTaskTypeEnum.storyboard.value],
        name="old-storyboard",
        base_url="https://old.example.com",
        api_key="old-key",
        model="old-model",
        is_active=True,
    )

    await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[AiTaskTypeEnum.extraction.value, AiTaskTypeEnum.storyboard.value],
        name="new-multi-purpose",
        base_url="https://new.example.com",
        api_key="new-key",
        model="new-model",
        is_active=True,
    ))

    await old_storyboard.refresh_from_db()
    assert old_storyboard.is_active is True


@pytest.mark.asyncio
async def test_创建配置_启用时同类型旧的继续运行():
    """创建新配置并启用，同类型下原有配置仍保持运行。"""
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
    assert old.is_active is True


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
async def test_全量更新配置_传入is_active不影响同类型():
    """全量更新时传 is_active=True，不影响同类型其他配置。"""
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
    assert active.is_active is True


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
async def test_局部更新配置_传入is_active不影响同类型():
    """局部更新传 is_active=True，不影响同类型其他配置。"""
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
    assert active.is_active is True


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
async def test_启用配置_同类型可同时运行():
    """启用新配置时，同 task_type 下其他已启用配置继续运行。"""
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
    assert c1.is_active is True

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
    assert ext1.is_active is True  # 同类型 ext 继续运行


@pytest.mark.asyncio
async def test_停用配置_只停止目标模型():
    """停用一个模型不会影响同用途下其他运行模型。"""
    first = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="deactivate-first",
        base_url="https://first.example.com",
        api_key="key-first",
        model="model-first",
        image_model_type="gpt_image_2",
        is_active=True,
    )
    second = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="deactivate-second",
        base_url="https://second.example.com",
        api_key="key-second",
        model="model-second",
        image_model_type="gpt_image_2",
        is_active=True,
    )

    result = await ai_model_config_controller.deactivate(second.id)

    await first.refresh_from_db()
    assert result.is_active is False
    assert first.is_active is True


# =====================================================================
# 获取启用配置
# =====================================================================

@pytest.mark.asyncio
async def test_获取启用配置():
    """get_active 返回指定类型下最近启用的配置。"""
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
async def test_获取指定的启用配置():
    """显式选择时返回目标模型，而不是自动选择的模型。"""
    first = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        task_types=[AiTaskTypeEnum.reference_image.value],
        name="image-first",
        base_url="https://first.example.com",
        api_key="key-first",
        model="model-first",
        image_model_type="gpt_image_2",
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        task_types=[AiTaskTypeEnum.reference_image.value],
        name="image-second",
        base_url="https://second.example.com",
        api_key="key-second",
        model="model-second",
        image_model_type="gpt_image_2",
        is_active=True,
    )

    result = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.reference_image.value,
        first.id,
    )

    assert result.id == first.id


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
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="key-v",
        model="model-v",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    )

    ext = await ai_model_config_controller.get_active(AiTaskTypeEnum.extraction.value)
    assert ext.name == "ext-active"

    vid = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)
    assert vid.name == "video-active"


@pytest.mark.asyncio
async def test_同一生图模型类型同时只能启用一个():
    first = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="seedream-lite-first",
        base_url="https://ark.example.com/api/v3",
        api_key="first-key",
        model="first-endpoint",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_lite",
        is_active=True,
    ))
    second = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="seedream-lite-second",
        base_url="https://ark.example.com/api/v3",
        api_key="second-key",
        model="second-endpoint",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_lite",
        is_active=True,
    ))
    pro = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="seedream-pro",
        base_url="https://ark.example.com/api/v3",
        api_key="pro-key",
        model="pro-endpoint",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        is_active=True,
    ))
    await first.refresh_from_db()
    await second.refresh_from_db()
    await pro.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert pro.is_active is True


@pytest.mark.asyncio
async def test_同一视频模型类型同时只能启用一个_不同类型可并行():
    first = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="seedance-2-first",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="first-key",
        model="first-endpoint",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    ))
    second = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="seedance-2-second",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="second-key",
        model="second-endpoint",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    ))
    fast = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="seedance-2-fast",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="fast-key",
        model="fast-endpoint",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2_fast",
        is_active=True,
    ))

    await first.refresh_from_db()
    await second.refresh_from_db()
    await fast.refresh_from_db()
    assert first.is_active is False
    assert second.is_active is True
    assert fast.is_active is True


@pytest.mark.asyncio
async def test_视频模型必须使用受支持类型和火山方舟协议():
    with pytest.raises(HTTPException, match="未选择受支持"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="missing-video-type",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="key",
            model="endpoint",
            api_protocol="volcengine_ark",
        ))

    minimax = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="minimax-h3",
        base_url="https://api.minimaxi.com",
        api_key="key",
        model="MiniMax-H3",
        api_protocol="minimax",
        video_model_type="minimax_h3",
    ))
    assert minimax.video_model_type == "minimax_h3"

    wan = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="wan3",
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com",
        api_key="key",
        model="wan3.0-video",
        api_protocol="dashscope",
        video_model_type="wan_3",
    ))
    assert wan.video_model_type == "wan_3"

    with pytest.raises(HTTPException, match="MiniMax 官方"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="minimax-wrong-protocol",
            base_url="https://api.minimaxi.com",
            api_key="key",
            model="MiniMax-H3",
            api_protocol="volcengine_ark",
            video_model_type="minimax_h3",
        ))

    with pytest.raises(HTTPException, match="仅支持火山方舟"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="wrong-protocol",
            base_url="https://example.com/v1",
            api_key="key",
            model="endpoint",
            api_protocol="openai_compatible",
            video_model_type="seedance_2_5",
        ))

    with pytest.raises(HTTPException, match="DashScope"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="wan-wrong-protocol",
            base_url="https://workspace.cn-beijing.maas.aliyuncs.com",
            api_key="key",
            model="wan3.0-video",
            api_protocol="volcengine_ark",
            video_model_type="wan_3",
        ))


@pytest.mark.asyncio
async def test_list_generation_capabilities_returns_all_types():
    capabilities = await ai_model_config_controller.list_generation_capabilities()
    assert "1K" in capabilities["image"]["seedream_5_pro"]
    assert "720p" in capabilities["video"]["seedance_2"]
    assert capabilities["video"]["wan_3"] == ["480P", "720P", "1080P"]
