import asyncio

import pytest
from fastapi import HTTPException
from tortoise.contrib.test import finalizer, initializer
from controllers.novel import novel_controller
from models.novel import Novel
from models.chapter import Chapter
from models.config import AiModelConfig
from schemas.novel import NovelCreate, NovelPatch, NovelUpdate, NovelOut
from utils.enums import AiTaskTypeEnum

@pytest.mark.asyncio
async def test_create_novel(sql_profiler):
    """Test creating a novel."""
    novel_in = NovelCreate(name="Test Novel", author="Test Author", content="Some content")

    async with sql_profiler as p:
        novel = await novel_controller.create(novel_in)

    assert novel.id is not None
    assert novel.name == "Test Novel"
    assert novel.author == "Test Author"

    # Check SQL queries
    print(f"\n[Create] SQL Count: {p.query_count}")
    # We expect at least an INSERT
    assert p.query_count > 0

@pytest.mark.asyncio
async def test_get_novel():
    """Test retrieving a novel."""
    novel = await Novel.create(name="Get Novel", author="Author", content="Content")

    fetched = await novel_controller.get(novel.id)
    assert fetched.id == novel.id
    assert fetched.name == "Get Novel"

@pytest.mark.asyncio
async def test_update_novel():
    """Test updating a novel."""
    novel = await Novel.create(name="Update Novel", author="Author")
    update_data = NovelUpdate(name="Updated Name", author="Author", content="New Content")

    updated = await novel_controller.update(novel.id, update_data)
    assert updated.name == "Updated Name"
    assert updated.content == "New Content"


@pytest.mark.asyncio
async def test_storyboard_video_model_preference_is_persisted_and_returned_by_meta():
    novel = await Novel.create(name="Persistent Video Model", author="Author")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        task_types=[AiTaskTypeEnum.video.value],
        name="preferred-video-model",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="k",
        model="video-model",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=True,
    )

    updated = await novel_controller.patch(
        novel.id,
        NovelPatch(video_model_config_id=config.id),
    )
    meta = await novel_controller.meta(novel.id)

    assert updated.video_model_config_id == config.id
    assert meta["video_model_config_id"] == config.id


@pytest.mark.asyncio
async def test_disabled_storyboard_video_model_preference_is_rejected():
    novel = await Novel.create(name="Disabled Video Model", author="Author")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        task_types=[AiTaskTypeEnum.video.value],
        name="disabled-video-model",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="k",
        model="video-model",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await novel_controller.patch(
            novel.id,
            NovelPatch(video_model_config_id=config.id),
        )

    assert exc_info.value.status_code == 400
    await novel.refresh_from_db()
    assert novel.video_model_config_id is None

@pytest.mark.asyncio
async def test_delete_novel():
    """Test deleting a novel."""
    novel = await Novel.create(name="Delete Novel", author="Author")
    await novel_controller.remove(novel.id)

    exists = await Novel.filter(id=novel.id).exists()
    assert not exists

@pytest.mark.asyncio
async def test_split_novel_chapters(sql_profiler):
    """Test splitting novel into chapters."""
    content = """
    第1章 开始
    这是第一章的内容。

    第2章 发展
    这是第二章的内容。
    """
    novel = await Novel.create(name="Split Novel", author="Author", content=content)

    async with sql_profiler as p:
        result_novel = await novel_controller.split(novel.id)

    assert result_novel.total_chapters == 2

    chapters = await Chapter.filter(novel_id=novel.id).order_by("number").all()
    assert len(chapters) == 2
    assert chapters[0].name == "开始"
    assert "第一章" in chapters[0].content
    assert chapters[1].name == "发展"
    assert "第二章" in chapters[1].content

    print(f"\n[Split] SQL Count: {p.query_count}")
    # Verify SQL efficiency (should likely insert chapters in batch or loop)


@pytest.mark.asyncio
async def test_split_novel_no_chapters_recognized():
    """无法识别章节时，整个小说作为一个章节。"""
    # 没有明确章节标记的内容
    content = "这是一段没有任何章节标记的纯文本内容，NLP无法识别出章节分割点。"
    novel = await Novel.create(name="No Chapter Novel", author="Author", content=content)

    result = await novel_controller.split(novel.id)
    assert result.total_chapters == 1

    chapters = await Chapter.filter(novel_id=novel.id).all()
    assert len(chapters) == 1
    assert chapters[0].name == "No Chapter Novel"
    assert chapters[0].content == content
    print(f"    无法识别章节，默认整体作为一个章节: name='{chapters[0].name}'")


@pytest.mark.asyncio
async def test_split_long_novel_rejects_single_chapter_fallback():
    """长书稿未识别出多个章节时直接失败，不得伪装成第一章。"""
    content = "这是一段没有章节标题的正文。" * 3_000
    novel = await Novel.create(name="Invalid Long Novel", author="Author", content=content)

    with pytest.raises(HTTPException) as exc_info:
        await novel_controller.split(novel.id)

    assert exc_info.value.status_code == 422
    assert "只识别到 0 章" in exc_info.value.detail
    assert await Chapter.filter(novel_id=novel.id).count() == 0


@pytest.mark.asyncio
async def test_split_rejects_mojibake_content():
    """包含大量 Unicode 替换字符的乱码正文不得进入工作流。"""
    content = ("\ufffd" * 100 + "乱码正文") * 400
    novel = await Novel.create(name="Mojibake Novel", author="Author", content=content)

    with pytest.raises(HTTPException) as exc_info:
        await novel_controller.split(novel.id)

    assert exc_info.value.status_code == 422
    assert "大量乱码" in exc_info.value.detail
    assert await Chapter.filter(novel_id=novel.id).count() == 0


@pytest.mark.asyncio
async def test_split_novel_already_has_chapters():
    """已有章节时禁止再次分章。"""
    content = "第1章 开始\n内容"
    novel = await Novel.create(name="Already Split Novel", author="Author", content=content)
    await Chapter.create(novel_id=novel.id, number=1, name="第1章 开始", content="内容")

    with pytest.raises(HTTPException) as exc_info:
        await novel_controller.split(novel.id)
    assert exc_info.value.status_code == 400
    assert "已有章节" in exc_info.value.detail
    print(f"    已有章节时拒绝分章: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_analyze_novel_submits_one_safe_task(configured_creation_agent):
    novel = await Novel.create(name="Analyze Novel", content="第1章 开始\n正文")
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.project_analysis.value,
        task_types=[AiTaskTypeEnum.project_analysis.value],
        name="llm",
        base_url="https://llm.example.com",
        api_key="secret-llm",
        model="llm-model",
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image",
        base_url="https://image.example.com",
        api_key="secret-image",
        model="image-model",
        image_model_type="gpt_image_2",
        is_active=True,
    )

    first = await novel_controller.analyze(novel.id)
    second = await novel_controller.analyze(novel.id)

    assert first.id == second.id
    assert first.task_type == AiTaskTypeEnum.project_analysis.value
    assert {key: first.request_params[key] for key in ("novel_id", "resolution", "prompt_language")} == {
        "novel_id": novel.id,
        "resolution": "1K",
        "prompt_language": "en",
    }
    assert first.request_params["workflow_version"] == "agent-skills-v1"
    assert first.request_params["skill_snapshot"]["revision"]
    assert "api_key" not in first.request_params


@pytest.mark.asyncio
async def test_analyze_novel_rejects_empty_content():
    novel = await Novel.create(name="Empty Analyze Novel", content="")
    with pytest.raises(HTTPException) as exc_info:
        await novel_controller.analyze(novel.id)
    assert exc_info.value.status_code == 400
    assert "书稿内容" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_same_title_allocates_distinct_projects_without_changing_existing():
    original = await Novel.create(name="同一本书", content="已有正文", team_id=8)
    first = await novel_controller.create(NovelCreate(name="同一本书", content="新正文"), team_id=8, created_by=9)
    second = await novel_controller.create(NovelCreate(name="同一本书", content="另一个版本"), team_id=8)

    assert first.name == "同一本书 (2)"
    assert second.name == "同一本书 (3)"
    assert first.team_id == 8
    assert first.created_by == 9
    assert first.content == "新正文"
    await original.refresh_from_db()
    assert original.name == "同一本书"
    assert original.content == "已有正文"


@pytest.mark.asyncio
async def test_create_same_max_length_title_preserves_name_limit():
    name = "书" * 255
    await Novel.create(name=name)

    novel = await novel_controller.create(NovelCreate(name=name))

    assert novel.name == "书" * 251 + " (2)"
    assert len(novel.name) == 255


@pytest.mark.asyncio
async def test_create_same_title_handles_competing_name_claim(monkeypatch):
    from tortoise.exceptions import IntegrityError
    from utils.crud import CRUDBase

    create = CRUDBase.create
    candidates = []

    async def racing_create(self, data, **kwargs):
        candidates.append(data["name"])
        if len(candidates) == 1:
            await Novel.create(name=data["name"], content="并发请求")
            raise IntegrityError("UNIQUE constraint failed: novels.name")
        return await create(self, data, **kwargs)

    monkeypatch.setattr(CRUDBase, "create", racing_create)
    novel = await novel_controller.create(NovelCreate(name="同时创建", content="本次正文"))

    assert novel.name == "同时创建 (2)"
    assert novel.content == "本次正文"
    assert candidates == ["同时创建", "同时创建 (2)"]
    assert await Novel.filter(name="同时创建").count() == 1


@pytest.mark.asyncio
async def test_create_does_not_hide_unrelated_integrity_errors(monkeypatch):
    from tortoise.exceptions import IntegrityError
    from utils.crud import CRUDBase

    async def invalid_create(self, data, **kwargs):
        raise IntegrityError("unrelated constraint")

    monkeypatch.setattr(CRUDBase, "create", invalid_create)
    with pytest.raises(IntegrityError, match="unrelated constraint"):
        await novel_controller.create(NovelCreate(name="其他约束错误"))


@pytest.mark.asyncio
async def test_concurrent_creates_keep_unique_names_and_separate_content():
    await Novel.create(name="并发书稿 (2)", content="已有版本")
    projects = await asyncio.gather(*[
        novel_controller.create(NovelCreate(name="并发书稿", content=f"正文 {index}"))
        for index in range(4)
    ])

    assert len({project.id for project in projects}) == 4
    assert {project.name for project in projects} == {
        "并发书稿", "并发书稿 (3)", "并发书稿 (4)", "并发书稿 (5)",
    }
    assert [project.content for project in projects] == [f"正文 {index}" for index in range(4)]
    assert (await Novel.get(name="并发书稿 (2)")).content == "已有版本"


@pytest.mark.asyncio
async def test_different_teams_can_keep_the_same_project_title():
    first = await novel_controller.create(NovelCreate(name="同一书名"), team_id=7, created_by=1)
    second = await novel_controller.create(NovelCreate(name="同一书名"), team_id=8, created_by=1)
    assert first.name == second.name == "同一书名"
    assert first.id != second.id


@pytest.mark.asyncio
async def test_team_members_share_the_team_name_scope():
    first = await novel_controller.create(NovelCreate(name="团队书名"), team_id=7, created_by=1)
    second = await novel_controller.create(NovelCreate(name="团队书名"), team_id=7, created_by=2)
    assert first.name == "团队书名"
    assert second.name == "团队书名 (2)"


@pytest.mark.asyncio
async def test_personal_projects_use_creator_scope_separate_from_teams_and_local_workspace():
    projects = [
        await novel_controller.create(NovelCreate(name="个人书名"), created_by=1),
        await novel_controller.create(NovelCreate(name="个人书名"), created_by=2),
        await novel_controller.create(NovelCreate(name="个人书名"), team_id=1, created_by=1),
        await novel_controller.create(NovelCreate(name="个人书名")),
    ]
    repeated = await novel_controller.create(NovelCreate(name="个人书名"), created_by=1)
    assert {project.name for project in projects} == {"个人书名"}
    assert repeated.name == "个人书名 (2)"


@pytest.mark.asyncio
async def test_database_enforces_names_within_scope_on_creates_and_renames():
    from tortoise.exceptions import IntegrityError

    for scope in ({"team_id": 7}, {"created_by": 1}, {}):
        first = await Novel.create(name="受约束名称", **scope)
        second = await Novel.create(name="可修改名称", **scope)
        with pytest.raises(IntegrityError):
            await Novel.create(name="受约束名称", **scope)
        with pytest.raises(IntegrityError):
            await Novel.filter(id=second.id).update(name=first.name)
