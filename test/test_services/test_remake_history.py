import pytest

from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from services.remake.history import RemakeHistoryCatalog
from utils.enums import TaskStatusEnum, VideoModelTypeEnum


@pytest.mark.asyncio
async def test_history_catalog_only_lists_projects_with_an_available_episode():
    available_project = await Novel.create(name="可复刻旧项目", author="作者", team_id=7)
    chapter = await Chapter.create(
        novel=available_project,
        number=1,
        name="第1集",
        content="",
    )
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="镜头", duration=5)
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/ready.mp4",
        metadata={"size_bytes": 2048},
    )
    scene.metadata = {"workbench": {"activeVideoId": video.id}}
    await scene.save(update_fields=["metadata", "updated_at"])

    empty_project = await Novel.create(name="空项目", author="作者", team_id=7)
    await Chapter.create(novel=empty_project, number=1, name="第1集", content="")
    other_team = await Novel.create(name="其他团队项目", author="作者", team_id=8)
    await Chapter.create(novel=other_team, number=1, name="第1集", content="")

    result = await RemakeHistoryCatalog().list_projects(
        team_id=7,
        allow_all=False,
        keyword="复刻",
        page=1,
        page_size=20,
    )

    assert result == {
        "items": [{
            "id": available_project.id,
            "name": "可复刻旧项目",
            "cover": None,
            "available_episode_count": 1,
        }],
        "pagination": {"total": 1, "page": 1, "page_size": 20, "pages": 1},
    }


@pytest.mark.asyncio
async def test_history_episode_availability_explains_incomplete_current_versions():
    project = await Novel.create(name="历史项目", author="作者")
    ready = await Chapter.create(novel=project, number=1, name="第1集", content="")
    ready_scene = await Scene.create(chapter=ready, sequence=1, prompt="镜头", duration=6)
    ready_video = await Video.create(
        scene=ready_scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/ready.mp4",
        metadata={"size_bytes": 4096},
    )
    ready_scene.metadata = {"workbench": {"activeVideoId": ready_video.id}}
    await ready_scene.save(update_fields=["metadata", "updated_at"])

    incomplete = await Chapter.create(novel=project, number=2, name="第2集", content="")
    incomplete_scene = await Scene.create(chapter=incomplete, sequence=1, prompt="镜头", duration=4)
    pending = await Video.create(
        scene=incomplete_scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.running.value,
    )
    incomplete_scene.metadata = {"workbench": {"activeVideoId": pending.id}}
    await incomplete_scene.save(update_fields=["metadata", "updated_at"])

    empty = await Chapter.create(novel=project, number=3, name="第3集", content="")

    episodes = await RemakeHistoryCatalog().list_episodes(project.id)

    assert episodes[0] == {
        "chapter_id": ready.id,
        "episode_number": 1,
        "name": "第1集",
        "duration_seconds": 6.0,
        "size_bytes": 4096,
        "scene_count": 1,
        "available": True,
        "unavailable_reason": None,
    }
    assert episodes[1]["available"] is False
    assert "镜头 1" in episodes[1]["unavailable_reason"]
    assert "当前视频" in episodes[1]["unavailable_reason"]
    assert episodes[2]["available"] is False
    assert episodes[2]["unavailable_reason"] == "章节暂无分镜"


@pytest.mark.asyncio
async def test_history_inspection_rejects_duration_and_size_limits():
    project = await Novel.create(name="超限项目", author="作者")
    chapter = await Chapter.create(novel=project, number=1, name="第1集", content="")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="镜头", duration=1201)
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/large.mp4",
        metadata={"size_bytes": 500 * 1024 * 1024 + 1},
    )
    scene.metadata = {"workbench": {"activeVideoId": video.id}}
    await scene.save(update_fields=["metadata", "updated_at"])

    episode = (await RemakeHistoryCatalog().list_episodes(project.id))[0]

    assert episode["available"] is False
    assert "20分钟" in episode["unavailable_reason"]
