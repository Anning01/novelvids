import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from controllers.video import video_controller
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.asset import Asset
from models.video import Video
from models.config import AiModelConfig
from schemas.video import VideoGenerateRequest
from utils.enums import (
    AiTaskTypeEnum,
    AssetTypeEnum,
    TaskStatusEnum,
    VideoModelTypeEnum,
)


# =====================================================================
# 辅助函数
# =====================================================================

async def _create_scene_with_config(
    prompt: str = "测试提示词",
    model_name: str = "viduq2",
) -> tuple[Scene, AiModelConfig]:
    """创建完整的 Scene + AiModelConfig 测试数据。"""
    novel = await Novel.create(name="Video Test Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt=prompt, duration=6.0)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name=model_name,
        base_url="https://mock.api.com/v2",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )
    return scene, config


# =====================================================================
# generate 方法
# =====================================================================

@pytest.mark.asyncio
async def test_生成视频_提交成功():
    """正常提交视频生成，返回 Video 记录。"""
    scene, config = await _create_scene_with_config()
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.viduq2.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "ext-task-001"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

    assert video.id is not None
    assert video.scene_id == scene.id
    assert video.model_type == VideoModelTypeEnum.viduq2.value
    assert video.external_task_id == "ext-task-001"
    assert video.status == TaskStatusEnum.pending.value
    print(f"    生成视频成功: video_id={video.id}, task_id={video.external_task_id}")


@pytest.mark.asyncio
async def test_生成视频_分镜不存在():
    """分镜ID不存在时报 404。"""
    req = VideoGenerateRequest(
        scene_id=99999,
        model_type=VideoModelTypeEnum.viduq2.value,
    )
    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)
    assert exc_info.value.status_code == 404
    assert "分镜" in exc_info.value.detail
    print(f"    分镜不存在: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_生成视频_无配置报404():
    """未配置视频模型时报 404。"""
    novel = await Novel.create(name="No Config Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)

    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.viduq2.value,
    )
    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)
    assert exc_info.value.status_code == 404
    assert "未配置" in exc_info.value.detail
    print(f"    无配置: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_生成视频_解析资产引用():
    """prompt 含 @资产昵称 时解析并传递 subjects。"""
    novel = await Novel.create(name="Asset Resolve Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
        aliases=["小张"],
    )
    scene = await Scene.create(
        chapter=chapter, sequence=1,
        prompt="@张三 在大殿中行走",
        duration=6.0,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="viduq2",
        base_url="https://mock.api.com/v2",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.viduq2.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "ext-task-002"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

        # 验证 submit 被调用时传递了 subjects
        call_kwargs = mock_gen.submit.call_args
        subjects = call_kwargs.kwargs.get("subjects") or call_kwargs[1].get("subjects")
        assert subjects is not None
        assert len(subjects) == 1
        assert subjects[0]["name"] == "张三"

    assert video.external_task_id == "ext-task-002"
    print(f"    解析资产引用: subjects={[s['name'] for s in subjects]}")


# =====================================================================
# query_status 方法
# =====================================================================

@pytest.mark.asyncio
async def test_查询视频状态_进行中():
    """查询进行中的任务，返回进度。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-001",
        status=TaskStatusEnum.pending.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.running,
            "progress": 50,
            "url": None,
            "metadata": {},
        }
        mock_factory.return_value = mock_gen

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.running.value
    print(f"    查询进行中: status={result.status}, video_id={result.id}")


@pytest.mark.asyncio
async def test_查询视频状态_已完成():
    """任务完成时更新 url 和 status。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-002",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/video.mp4",
            "metadata": {"duration": 6.0},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"./media/videos/{video.id}.mp4"

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.completed.value
    assert result.url == f"./media/videos/{video.id}.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/video.mp4", video.id)
    print(f"    查询已完成: url={result.url}")


@pytest.mark.asyncio
async def test_查询视频状态_已完成不再查询():
    """已完成的视频不再调用外部 API。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-003",
        status=TaskStatusEnum.completed.value,
        url="https://cdn.example.com/done.mp4",
    )

    # 不应调用 get_generator
    result = await video_controller.query_status(video.id)
    assert result.status == TaskStatusEnum.completed.value
    assert result.url == "https://cdn.example.com/done.mp4"
    print(f"    已完成不再查询: url={result.url}")


@pytest.mark.asyncio
async def test_查询视频状态_失败():
    """任务失败时更新 status。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-004",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.failed,
            "progress": None,
            "url": None,
            "metadata": {"err_code": "timeout"},
        }
        mock_factory.return_value = mock_gen

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.failed.value
    print(f"    查询失败: status={result.status}")


# =====================================================================
# 边界情况
# =====================================================================

@pytest.mark.asyncio
async def test_查询视频_无外部任务ID():
    """无 external_task_id 时报 400。"""
    scene, _ = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.pending.value,
        external_task_id=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.query_status(video.id)
    assert exc_info.value.status_code == 400
    assert "外部任务ID" in exc_info.value.detail
    print(f"    无外部任务ID: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_查询视频_配置不存在():
    """查询时配置已被删除报 404。"""
    novel = await Novel.create(name="No Cfg Query Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)
    # 不创建 AiModelConfig
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="orphan-task",
        status=TaskStatusEnum.pending.value,
    )

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.query_status(video.id)
    assert exc_info.value.status_code == 404
    assert "配置不存在" in exc_info.value.detail
    print(f"    配置不存在: {exc_info.value.detail}")


# =====================================================================
# CRUD
# =====================================================================

@pytest.mark.asyncio
async def test_删除视频():
    """删除视频后不再存在。"""
    scene, _ = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.pending.value,
    )

    await video_controller.remove(video.id)
    exists = await Video.filter(id=video.id).exists()
    assert not exists
    print(f"    删除视频: video_id={video.id}")
