import pytest
from tortoise.contrib.test import finalizer, initializer
from controllers.novel import novel_controller
from models.novel import Novel
from models.chapter import Chapter
from schemas.novel import NovelCreate, NovelUpdate, NovelOut

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
    assert chapters[0].name == "第1章 开始"
    assert "第一章" in chapters[0].content
    assert chapters[1].name == "第2章 发展"
    assert "第二章" in chapters[1].content

    print(f"\n[Split] SQL Count: {p.query_count}")
    # Verify SQL efficiency (should likely insert chapters in batch or loop)
