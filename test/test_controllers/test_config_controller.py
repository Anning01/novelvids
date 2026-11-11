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
async def test_重制能力可与普通文本能力共用配置():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[
            AiTaskTypeEnum.extraction.value,
            AiTaskTypeEnum.remake_decomposition.value,
        ],
        name="shared-multimodal-model",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="multimodal-model",
    ))

    assert config.task_types == [
        AiTaskTypeEnum.extraction.value,
        AiTaskTypeEnum.remake_decomposition.value,
    ]


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
async def test_重制拆解解析显式声明能力的共享LLM配置():
    shared_text = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[
            AiTaskTypeEnum.extraction.value,
            AiTaskTypeEnum.remake_decomposition.value,
        ],
        name="recent-text-model",
        base_url="https://text.example.com/v1",
        api_key="text-key",
        model="text-only",
        is_active=True,
    )
    resolved = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.remake_decomposition.value
    )

    assert resolved.id == shared_text.id


@pytest.mark.asyncio
async def test_重制拆解可显式选择共享LLM配置():
    shared_text = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        task_types=[
            AiTaskTypeEnum.extraction.value,
            AiTaskTypeEnum.remake_decomposition.value,
        ],
        name="shared-text-model",
        base_url="https://text.example.com/v1",
        api_key="text-key",
        model="text-only",
        is_active=True,
    )

    resolved = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.remake_decomposition.value,
        shared_text.id,
    )

    assert resolved.id == shared_text.id


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
async def test_同一生图模型类型的多个渠道可同时启用():
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
    assert first.is_active is True
    assert second.is_active is True
    assert pro.is_active is True


@pytest.mark.asyncio
async def test_同一视频模型类型的多个渠道和不同类型可同时启用():
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
    assert first.is_active is True
    assert second.is_active is True
    assert fast.is_active is True


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "activate", "patch", "update"])
@pytest.mark.parametrize("task_type,model_type_field,model_type", [
    (AiTaskTypeEnum.video.value, "video_model_type", "seedance_2_mini"),
    (AiTaskTypeEnum.reference_image.value, "image_model_type", "seedream_5_lite"),
])
async def test_渠道配置独立启停并按配置ID选择(operation, task_type, model_type_field, model_type):
    payload = dict(task_type=task_type, task_types=[task_type], base_url="https://models.example.test/api/v3",
        api_key="test-key", model="configured-model", api_protocol="volcengine_ark", **{model_type_field: model_type})
    kind = "video" if task_type == AiTaskTypeEnum.video.value else "image"
    prices = {"480p": 23} if kind == "video" else {"2K": 0.4}
    first = await ai_model_config_controller.create(AiModelConfigCreate(**payload, name="官方渠道", is_active=True,
        pricing={"type": kind, "prices": prices, "discount": 1}))
    second_input = AiModelConfigCreate(**payload, name="优惠渠道", is_active=operation == "create",
        pricing={"type": kind, "prices": prices, "discount": 0.5})
    second = await ai_model_config_controller.create(second_input)
    if operation == "activate":
        await ai_model_config_controller.activate(second.id)
    elif operation == "patch":
        await ai_model_config_controller.patch(second.id, AiModelConfigPatch(is_active=True))
    elif operation == "update":
        await ai_model_config_controller.update(second.id, AiModelConfigUpdate(**{
            **second_input.model_dump(exclude_unset=True), "is_active": True,
        }))
    for config in (first, second):
        await config.refresh_from_db()
        assert config.is_active is True
        assert (await ai_model_config_controller.get_active(task_type, config.id)).id == config.id
    models = await (ai_model_config_controller.list_active_video_models() if kind == "video"
        else ai_model_config_controller.list_active_image_models())
    assert {model["config_id"] for model in models} == {first.id, second.id}
    assert first.pricing["discount"] == 1
    assert second.pricing["discount"] == 0.5
    await ai_model_config_controller.deactivate(second.id)
    await first.refresh_from_db()
    await second.refresh_from_db()
    assert first.is_active is True
    assert second.is_active is False


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
    for model_type in ("gpt_image_2", "gpt_image_2_5", "gpt_image_2_6", "gpt_image_2_6_sunburst", "gpt_image_2_6_flare"):
        assert capabilities["image"][model_type] == ["1K", "2K", "4K"]
    for model_type in ("gpt_image_2_5", "gpt_image_2_6", "gpt_image_2_6_sunburst", "gpt_image_2_6_flare"):
        assert capabilities["image_protocols"][model_type] == ["openai_compatible", "novelvids"]


@pytest.mark.parametrize("model_type", ["gpt_image_2_5", "gpt_image_2_6", "gpt_image_2_6_sunburst", "gpt_image_2_6_flare"])
async def test_gpt_image_config_survives_safe_schema_initialization_and_provider_change(model_type):
    from tortoise import Tortoise

    legacy = await AiModelConfig.create(task_type=2, task_types=[2], name="legacy",
        base_url="https://legacy.example/v1", api_key="legacy-key", model="gpt-image-2",
        image_model_type="gpt_image_2", is_active=True)
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=2, task_types=[2], name=model_type, base_url="https://provider.example/v1",
        api_key="test-key", model="supplier-model-alias", image_model_type=model_type,
        api_protocol="openai_compatible", is_active=True))
    for _ in range(2):
        await Tortoise.generate_schemas(safe=True)
    await legacy.refresh_from_db()
    assert legacy.model == "gpt-image-2"
    assert legacy.base_url == "https://legacy.example/v1"
    assert legacy.is_active is True
    assert await AiModelConfig.filter(id=config.id).count() == 1
    configs = await ai_model_config_controller.list_active_image_models()
    current = next(item for item in configs if item["config_id"] == config.id)
    assert current["capabilities"]["clarities"] == ["1K", "2K", "4K"]
    assert next(item for item in configs if item["config_id"] == legacy.id)["capabilities"]["clarities"] == ["1K", "2K", "4K"]
    await ai_model_config_controller.patch(config.id, AiModelConfigPatch(base_url="https://replacement.example/custom/v1"))
    await config.refresh_from_db()
    assert config.base_url == "https://replacement.example/custom/v1"
    assert config.model == "supplier-model-alias"


async def test_legacy_gpt_quality_prices_require_explicit_resolution_prices():
    from tortoise import Tortoise

    old_prices = {"type": "image", "prices": {"low": 0.06, "medium": 0.08, "high": 0.16}}
    config = await AiModelConfig.create(task_type=2, task_types=[2], name="GPT Image 2",
        base_url="https://provider.example/v1", api_key="test", model="gpt-image-2",
        image_model_type="gpt_image_2", is_active=True, pricing=old_prices)
    for _ in range(2):
        await Tortoise.generate_schemas(safe=True)
    with pytest.raises(HTTPException, match="清晰度"):
        await ai_model_config_controller.get_active(2, config.id)
    await config.refresh_from_db()
    assert config.pricing == old_prices
    new_prices = {"type": "image", "prices": {"1K": 0.1, "2K": 0.2, "4K": 0.4}}
    await ai_model_config_controller.patch(config.id, AiModelConfigPatch(pricing=new_prices))
    assert (await ai_model_config_controller.get_active(2, config.id)).pricing == new_prices


@pytest.mark.parametrize("prices", [{"1K": 0.1, "2K": 0.2}, {"1K": 0.1, "2K": 0.2, "4K": float("nan")}])
async def test_gpt_image_rejects_incomplete_or_invalid_resolution_prices(prices):
    with pytest.raises(HTTPException):
        await ai_model_config_controller.create(AiModelConfigCreate(task_type=2, task_types=[2],
            name="GPT", model="gpt-image-2", image_model_type="gpt_image_2",
            base_url="https://provider.example/v1", api_key="test", pricing={"type": "image", "prices": prices}))
