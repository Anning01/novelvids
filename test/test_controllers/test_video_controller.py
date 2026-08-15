import pytest
from unittest.mock import AsyncMock, patch
from decimal import Decimal
from fastapi import HTTPException

from controllers.video import video_controller
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.usage_record import ModelUsageRecord
from models.video import Video
from models.config import AiModelConfig
from schemas.video import VideoGenerateRequest, VideoReferenceMedia
from services.video.base import VideoProviderError
from services.video.reference_media import reference_mention_syntax
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
    model_name: str = "seedance-2",
) -> tuple[Scene, AiModelConfig]:
    """创建完整的 Scene + AiModelConfig 测试数据。"""
    novel = await Novel.create(name="Video Test Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt=prompt, duration=6.0)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name=model_name,
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="sk-test",
        model="mock-model",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
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
        model_config_id=config.id,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "ext-task-001"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

    assert video.id is not None
    assert video.scene_id == scene.id
    assert video.model_type == VideoModelTypeEnum.seedance.value
    assert video.metadata["model_config_id"] == config.id
    assert video.metadata["model_name"] == config.name
    assert video.metadata["model"] == config.model
    assert video.metadata["video_model_type"] == "seedance_2"
    assert video.external_task_id == "ext-task-001"
    assert video.status == TaskStatusEnum.pending.value
    await scene.refresh_from_db()
    assert scene.metadata["current_video_id"] == video.id
    print(f"    生成视频成功: video_id={video.id}, task_id={video.external_task_id}")


@pytest.mark.asyncio
async def test_生成视频_供应商提交失败时持久化异常记录():
    """供应商同步拒绝请求时，失败详情仍能在预览区与状态轨道中恢复。"""
    scene, config = await _create_scene_with_config()
    req = VideoGenerateRequest(scene_id=scene.id, model_config_id=config.id)

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.side_effect = VideoProviderError(
            "视频供应商请求失败：参考图片格式不受支持（HTTP 400，request_id=req-test）"
        )
        mock_factory.return_value = mock_gen
        video = await video_controller.generate(req)

    assert video.status == TaskStatusEnum.failed.value
    assert video.external_task_id is None
    assert video.metadata["error"] == (
        "视频供应商请求失败：参考图片格式不受支持（HTTP 400，request_id=req-test）"
    )
    persisted = await Video.get(id=video.id)
    assert persisted.status == TaskStatusEnum.failed.value
    assert persisted.metadata["error"] == video.metadata["error"]


@pytest.mark.asyncio
async def test_生成视频_传递并记录参考图片和视频():
    image = VideoReferenceMedia(type="image", url="https://cdn.example.com/look.png", width=1024, height=1024)
    motion = VideoReferenceMedia(type="video", url="https://cdn.example.com/motion.mp4", duration=8, width=1280, height=720)
    scene, config = await _create_scene_with_config(
        prompt=f"使用 {reference_mention_syntax('image', image.url)} 和 {reference_mention_syntax('video', motion.url)}"
    )
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=config.id,
        reference_media=[image, motion],
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "reference-task"
        mock_factory.return_value = mock_gen
        video = await video_controller.generate(req)

    kwargs = mock_gen.submit.call_args.kwargs
    assert kwargs["reference_images"] == ["https://cdn.example.com/look.png"]
    assert kwargs["reference_videos"] == ["https://cdn.example.com/motion.mp4"]
    assert video.metadata["reference_media"][1]["duration"] == 8.0


@pytest.mark.asyncio
async def test_生成视频_未在提示词引用的上传素材不会提交供应商():
    scene, config = await _create_scene_with_config(prompt="只生成空镜头")
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=config.id,
        reference_media=[
            VideoReferenceMedia(type="image", url="https://cdn.example.com/person.png"),
            VideoReferenceMedia(type="video", url="https://cdn.example.com/motion.mp4", duration=8),
        ],
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "no-reference-task"
        mock_factory.return_value = mock_gen
        video = await video_controller.generate(req)

    kwargs = mock_gen.submit.call_args.kwargs
    assert kwargs["reference_images"] == []
    assert kwargs["reference_videos"] == []
    assert video.metadata["reference_media"] == []


@pytest.mark.asyncio
async def test_首尾帧模式_拒绝全模态参考素材():
    scene, config = await _create_scene_with_config()
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=config.id,
        generation_mode="keyframes",
        first_frame_url="https://cdn.example.com/first.png",
        last_frame_url="https://cdn.example.com/last.png",
        reference_media=[VideoReferenceMedia(type="image", url="https://cdn.example.com/reference.png")],
    )

    with pytest.raises(HTTPException, match="不能同时"):
        await video_controller.generate(req)


@pytest.mark.asyncio
async def test_生成视频_分镜不存在():
    """分镜ID不存在时报 404。"""
    req = VideoGenerateRequest(
        scene_id=99999,
        model_config_id=1,
    )
    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)
    assert exc_info.value.status_code == 404
    assert "分镜" in exc_info.value.detail
    print(f"    分镜不存在: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_生成视频_未选择可用配置报400():
    """提交不存在或未启用的视频配置时报 400。"""
    novel = await Novel.create(name="No Config Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)

    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=99999,
    )
    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)
    assert exc_info.value.status_code == 400
    assert "未启用或已被删除" in exc_info.value.detail
    print(f"    无配置: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_生成视频_解析资产引用():
    """prompt 含 @资产昵称 时解析并传递 subjects。"""
    novel = await Novel.create(name="Asset Resolve Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    asset = await Asset.create(
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
    await scene.assets.add(asset)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="seedance-2",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="sk-test",
        model="mock-model",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    )
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=config.id,
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


@pytest.mark.asyncio
async def test_生成视频_采用分镜选择的资产衍生状态():
    """分镜 metadata 中的形态选择决定实际提交的参考图片。"""
    novel = await Novel.create(name="Scene Variant Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=3, name="第3章", content="内容")
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="艾伦",
        main_image="https://example.com/base.png",
    )
    variant = await AssetVariant.create(
        asset=asset,
        name="负伤形态",
        images=["https://example.com/injured.png"],
    )
    scene = await Scene.create(
        chapter=chapter,
        sequence=1,
        prompt="@艾伦 走入画面",
        duration=6.0,
        metadata={"asset_variant_ids": {str(asset.id): variant.id}},
    )
    await scene.assets.add(asset)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="seedance-2-variant",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="sk-test",
        model="mock-model",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "variant-task-001"
        mock_factory.return_value = mock_gen
        await video_controller.generate(VideoGenerateRequest(
            scene_id=scene.id,
            model_config_id=config.id,
        ))

    subjects = mock_gen.submit.call_args.kwargs["subjects"]
    assert subjects[0]["variant_name"] == "负伤形态"
    assert subjects[0]["images"] == ["https://example.com/injured.png"]


@pytest.mark.asyncio
async def test_首尾帧生成_必须同时提供两张图片():
    """首尾帧模式缺少任意一帧时，不提交外部生成任务。"""
    scene, config = await _create_scene_with_config()
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=config.id,
        generation_mode="keyframes",
        first_frame_url="https://cdn.example.com/first.png",
    )

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)

    assert exc_info.value.status_code == 400
    assert "首帧和尾帧" in exc_info.value.detail


@pytest.mark.asyncio
async def test_首尾帧生成_传递关键帧并记录模式():
    """首尾帧地址传给视频生成器，并写入视频元数据。"""
    scene, config = await _create_scene_with_config()
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_config_id=config.id,
        generation_mode="keyframes",
        first_frame_url="https://cdn.example.com/first.png",
        last_frame_url="https://cdn.example.com/last.png",
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "keyframe-task-001"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

    kwargs = mock_gen.submit.call_args.kwargs
    assert kwargs["generation_mode"] == "keyframes"
    assert kwargs["first_frame_url"] == "https://cdn.example.com/first.png"
    assert kwargs["last_frame_url"] == "https://cdn.example.com/last.png"
    assert kwargs["subjects"] is None
    assert video.metadata["generation_mode"] == "keyframes"


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
async def test_返回尾帧_注入同章下一分镜参考图():
    scene, config = await _create_scene_with_config()
    next_scene = await Scene.create(
        chapter_id=scene.chapter_id,
        sequence=2,
        prompt="下一镜头",
        duration=6.0,
        metadata={"video_reference_media": [{"type": "image", "url": "https://cdn.example.com/manual.png"}]},
    )
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="return-last-frame-task",
        status=TaskStatusEnum.running.value,
        metadata={
            "model_config_id": config.id,
            "video_model_type": "seedance_2",
            "return_last_frame": True,
        },
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_video_download, \
         patch("controllers.video._download_last_frame", new_callable=AsyncMock) as mock_frame_download:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/video.mp4",
            "metadata": {"last_frame_url": "https://cdn.example.com/last.png"},
        }
        mock_factory.return_value = mock_gen
        mock_video_download.return_value = f"/media/videos/{video.id}.mp4"
        mock_frame_download.return_value = f"/media/video-references/last-frame-{video.id}.png"
        result = await video_controller.query_status(video.id)

    await next_scene.refresh_from_db()
    references = next_scene.metadata["video_reference_media"]
    assert references[0]["url"] == f"/media/video-references/last-frame-{video.id}.png"
    assert references[0]["source_scene_id"] == scene.id
    assert references[1]["url"] == "https://cdn.example.com/manual.png"
    assert result.metadata["last_frame_injected_scene_id"] == next_scene.id


@pytest.mark.asyncio
async def test_返回尾帧_章节末镜头注入下一章首镜头():
    scene, config = await _create_scene_with_config()
    chapter = await Chapter.get(id=scene.chapter_id)
    next_chapter = await Chapter.create(
        novel_id=chapter.novel_id,
        number=chapter.number + 1,
        name="下一章",
        content="内容",
    )
    next_scene = await Scene.create(
        chapter=next_chapter,
        sequence=1,
        prompt="跨章镜头",
        duration=6.0,
    )
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="cross-chapter-last-frame-task",
        status=TaskStatusEnum.running.value,
        metadata={
            "model_config_id": config.id,
            "video_model_type": "seedance_2",
            "return_last_frame": True,
        },
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_video_download, \
         patch("controllers.video._download_last_frame", new_callable=AsyncMock) as mock_frame_download:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/video.mp4",
            "metadata": {"last_frame_url": "https://cdn.example.com/cross-last.png"},
        }
        mock_factory.return_value = mock_gen
        mock_video_download.return_value = f"/media/videos/{video.id}.mp4"
        mock_frame_download.return_value = f"/media/video-references/last-frame-{video.id}.png"
        await video_controller.query_status(video.id)

    await next_scene.refresh_from_db()
    assert next_scene.metadata["video_reference_media"][0]["source_scene_id"] == scene.id


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


@pytest.mark.asyncio
async def test_查询视频状态_配置停用后仍使用任务原配置():
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="disabled-config-task",
        status=TaskStatusEnum.running.value,
        metadata={"model_config_id": config.id, "video_model_type": "seedance_2"},
    )
    config.is_active = False
    await config.save(update_fields=["is_active"])

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
    assert mock_factory.call_args.args[0].id == config.id


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
    assert "启用一个模型" in exc_info.value.detail
    print(f"    配置不存在: {exc_info.value.detail}")


# =====================================================================
# CRUD
# =====================================================================

@pytest.mark.asyncio
async def test_视频生成记录按时间倒序并可恢复成功版本():
    scene, _ = await _create_scene_with_config()
    completed = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/completed.mp4",
    )
    failed = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.failed.value,
        metadata={"error": "provider rejected"},
    )
    scene.metadata = {"current_video_id": failed.id, "preserved": True}
    await scene.save(update_fields=["metadata", "updated_at"])

    history = await video_controller.generation_history(scene.id)
    selected = await video_controller.select_current(completed.id)

    assert [record.id for record in history] == [failed.id, completed.id]
    assert selected.id == completed.id
    await scene.refresh_from_db()
    assert scene.metadata == {"current_video_id": completed.id, "preserved": True}


@pytest.mark.asyncio
async def test_未完成视频不能设为当前版本():
    scene, _ = await _create_scene_with_config()
    pending = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.pending.value,
    )

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.select_current(pending.id)

    assert exc_info.value.status_code == 400
    assert "已完成" in exc_info.value.detail

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


class FakeCompletedGenerator:
    async def query(self, external_task_id: str) -> dict:
        return {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://example.com/v.mp4",
            "metadata": {"duration": 5},
        }


@pytest.mark.asyncio
async def test_query_status_completed_落视频流水():
    novel = await Novel.create(name="视频计费小说", author="a")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第1章", content="c")
    scene = await Scene.create(chapter_id=chapter.id, sequence=1, description="d", prompt="p", duration=6)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video", base_url="https://ark.cn-beijing.volces.com/api/v3", api_key="k", model="v",
        api_protocol="volcengine_ark", video_model_type="seedance_2",
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 46.0}},
        is_active=True,
    )
    video = await Video.create(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="ext-1",
        status=TaskStatusEnum.pending.value,
        metadata={"model_config_id": config.id, "novel_id": novel.id, "resolution": "720p", "duration": 5},
    )
    with (
        patch("controllers.video.get_generator", return_value=FakeCompletedGenerator()),
        patch("controllers.video._download_video", new=AsyncMock(return_value="/media/videos/1.mp4")),
    ):
        await video_controller.query_status(video.id)

    record = await ModelUsageRecord.filter(video_id=video.id).first()
    assert record is not None
    assert record.billing_type == "video"
    assert record.status == TaskStatusEnum.completed.value
    assert record.cost == Decimal("4.968000")  # 46 × 21600 token/s × 5s / 1e6


@pytest.mark.asyncio
async def test_query_status_completed_video_reference_uses_ref_price():
    novel = await Novel.create(name="视频参考计费小说", author="a")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第1章", content="c")
    scene = await Scene.create(chapter_id=chapter.id, sequence=1, description="d", prompt="p", duration=6)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video", base_url="https://ark.cn-beijing.volces.com/api/v3", api_key="k", model="v",
        api_protocol="volcengine_ark", video_model_type="seedance_2",
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 46.0}, "video_reference_prices": {"720p": 28.0}},
        is_active=True,
    )
    video = await Video.create(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="ext-2",
        status=TaskStatusEnum.pending.value,
        metadata={"model_config_id": config.id, "novel_id": novel.id, "resolution": "720p", "duration": 5, "has_video_reference": True, "input_video_seconds": 3},
    )
    with (
        patch("controllers.video.get_generator", return_value=FakeCompletedGenerator()),
        patch("controllers.video._download_video", new=AsyncMock(return_value="/media/videos/2.mp4")),
    ):
        await video_controller.query_status(video.id)

    record = await ModelUsageRecord.filter(video_id=video.id).first()
    assert record is not None
    assert record.usage["has_video_reference"] is True
    assert record.usage["input_video_seconds"] == 3
    assert record.cost == Decimal("4.838400")  # 28 × 21600 token/s × (5+3)s / 1e6
