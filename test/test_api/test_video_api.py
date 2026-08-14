import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.video import Video
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum, TaskStatusEnum, VideoModelTypeEnum


async def _setup_video_data(
    model_name: str = "seedance-2",
) -> tuple[Scene, AiModelConfig]:
    """创建测试用 Scene + Config。"""
    novel = await Novel.create(name="API Video Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="测试", duration=6.0)
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


@pytest.mark.asyncio
async def test_api_生成视频(client: AsyncClient):
    """POST /api/video/generate/ 成功返回 Video。"""
    scene, config = await _setup_video_data()

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "api-task-001"
        mock_factory.return_value = mock_gen

        resp = await client.post("/api/video/generate/", json={
            "scene_id": scene.id,
            "model_config_id": config.id,
        })

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["external_task_id"] == "api-task-001"
    assert data["status"] == TaskStatusEnum.pending.value
    print(f"    API 生成视频: id={data['id']}, task_id={data['external_task_id']}")


@pytest.mark.asyncio
async def test_api_上传参考素材使用所选模型能力(client: AsyncClient):
    _, config = await _setup_video_data()
    uploaded = {
        "type": "video",
        "url": "/media/video-references/reference.mp4",
        "name": "reference.mp4",
        "content_type": "video/mp4",
        "size_bytes": 1024,
        "width": 1280,
        "height": 720,
        "duration": 8,
        "fps": 30,
        "codec": "h264",
    }

    with patch("api.video.save_reference_upload", new_callable=AsyncMock, return_value=uploaded) as save:
        resp = await client.post(
            "/api/video/reference/upload",
            data={"model_config_id": str(config.id)},
            files={"file": ("reference.mp4", b"video", "video/mp4")},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"] == uploaded
    assert save.await_args.args[1].max_reference_videos == 3


@pytest.mark.asyncio
async def test_api_查询视频状态(client: AsyncClient):
    """GET /api/video/query/{id} 返回进度。"""
    scene, config = await _setup_video_data()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="api-query-001",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/video.mp4",
            "metadata": {},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"./media/videos/{video.id}.mp4"

        resp = await client.get(f"/api/video/query/{video.id}")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == TaskStatusEnum.completed.value
    assert data["url"] == f"./media/videos/{video.id}.mp4"
    print(f"    API 查询状态: status={data['status']}, url={data['url']}")


@pytest.mark.asyncio
async def test_api_获取视频列表(client: AsyncClient):
    """GET /api/video/ 返回视频列表。"""
    scene, _ = await _setup_video_data()
    await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.completed.value,
        url="https://cdn.example.com/1.mp4",
    )
    await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.veo3.value,
        status=TaskStatusEnum.pending.value,
    )

    resp = await client.get("/api/video")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["pagination"]["total"] == 2
    print(f"    API 视频列表: total={data['pagination']['total']}")


@pytest.mark.asyncio
async def test_api_获取视频详情(client: AsyncClient):
    """GET /api/video/{id} 返回完整信息。"""
    scene, _ = await _setup_video_data()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="detail-001",
        status=TaskStatusEnum.completed.value,
        url="https://cdn.example.com/detail.mp4",
    )

    resp = await client.get(f"/api/video/{video.id}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["id"] == video.id
    assert data["url"] == "https://cdn.example.com/detail.mp4"
    print(f"    API 视频详情: id={data['id']}, url={data['url']}")


@pytest.mark.asyncio
async def test_api_获取生成记录并恢复当前视频版本(client: AsyncClient):
    scene, _ = await _setup_video_data()
    completed = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/history.mp4",
    )
    failed = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.failed.value,
        metadata={"error": "provider rejected"},
    )

    history_resp = await client.get(f"/api/video/scene/{scene.id}/generation-history")
    select_resp = await client.post(f"/api/video/{completed.id}/select-current")

    assert history_resp.status_code == 200, history_resp.text
    assert [record["id"] for record in history_resp.json()["data"]] == [failed.id, completed.id]
    assert select_resp.status_code == 200, select_resp.text
    assert select_resp.json()["data"]["id"] == completed.id
    await scene.refresh_from_db()
    assert scene.metadata["current_video_id"] == completed.id


@pytest.mark.asyncio
async def test_api_删除视频(client: AsyncClient):
    """DELETE /api/video/{id} 成功。"""
    scene, _ = await _setup_video_data()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.pending.value,
    )

    resp = await client.delete(f"/api/video/{video.id}")
    assert resp.status_code == 200, resp.text
    exists = await Video.filter(id=video.id).exists()
    assert not exists
    print(f"    API 删除视频: video_id={video.id}")


@pytest.mark.asyncio
async def test_api_生成视频_未选择可用配置(client: AsyncClient):
    """提交不存在或未启用的视频配置时返回 400。"""
    novel = await Novel.create(name="No Cfg Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)

    resp = await client.post("/api/video/generate/", json={
        "scene_id": scene.id,
        "model_config_id": 99999,
    })
    body = resp.json()
    assert body["code"] == 400
    assert "未启用或已被删除" in body["message"]
    print(f"    API 无配置: code={body['code']}, message={body['message']}")


@pytest.mark.asyncio
async def test_api_拒绝旧供应商枚举选择(client: AsyncClient):
    scene, config = await _setup_video_data()

    resp = await client.post("/api/video/generate/", json={
        "scene_id": scene.id,
        "model_config_id": config.id,
        "model_type": VideoModelTypeEnum.viduq2.value,
    })

    assert resp.status_code == 200
    assert resp.json()["code"] == 422
    assert "model_type" in resp.json()["message"]
