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
    model_name: str = "viduq2",
) -> tuple[Scene, AiModelConfig]:
    """创建测试用 Scene + Config。"""
    novel = await Novel.create(name="API Video Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="测试", duration=6.0)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name=model_name,
        base_url="https://mock.api.com/v2",
        api_key="sk-test",
        model="mock-model",
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
            "model_type": VideoModelTypeEnum.viduq2.value,
        })

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["external_task_id"] == "api-task-001"
    assert data["status"] == TaskStatusEnum.pending.value
    print(f"    API 生成视频: id={data['id']}, task_id={data['external_task_id']}")


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
async def test_api_生成视频_无配置(client: AsyncClient):
    """无配置时返回 404。"""
    novel = await Novel.create(name="No Cfg Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)

    resp = await client.post("/api/video/generate/", json={
        "scene_id": scene.id,
        "model_type": VideoModelTypeEnum.viduq2.value,
    })
    body = resp.json()
    assert body["code"] == 404
    assert "未配置" in body["message"]
    print(f"    API 无配置: code={body['code']}, message={body['message']}")
