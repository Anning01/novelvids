import pytest
from controllers.chapter import chapter_controller
from models.novel import Novel
from models.chapter import Chapter
from schemas.chapter import ChapterCreate, ChapterUpdate

@pytest.mark.asyncio
async def test_create_chapter(sql_profiler):
    """Test creating a chapter."""
    novel = await Novel.create(name="Chapter Test Novel", author="Author")

    chapter_in = ChapterCreate(
        novel_id=novel.id,
        number=1,
        name="First Chapter",
        content="Chapter Content"
    )

    # Note: Chapter model requires novel_id.
    # The controller's create method (inherited from CRUDBase) accepts kwargs.
    # We must pass novel_id here because it's not in the schema.
    async with sql_profiler as p:
        chapter = await chapter_controller.create(chapter_in)

    assert chapter.id is not None
    assert chapter.name == "First Chapter"
    assert chapter.novel_id == novel.id
    assert p.query_count > 0

@pytest.mark.asyncio
async def test_get_chapter():
    """Test retrieving a chapter."""
    novel = await Novel.create(name="Get Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="Get Chapter",
        content="Content"
    )

    fetched = await chapter_controller.get(chapter.id)
    assert fetched.id == chapter.id
    assert fetched.name == "Get Chapter"

@pytest.mark.asyncio
async def test_update_chapter():
    """Test updating a chapter."""
    novel = await Novel.create(name="Update Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="Old Name",
        content="Old Content"
    )

    update_data = ChapterUpdate(
        novel_id=novel.id,
        number=1,
        name="Updated Name",
        content="New Content"
    )

    # The controller logic in controllers/chapter.py overrides update
    # signature: async def update(self, novel_id: int, obj_in: ChapterUpdate) -> Chapter:
    # Wait, the signature says `novel_id` but it calls `self.get(novel_id)`.
    # It seems the argument name is `novel_id` but it expects the `id` (chapter_id).
    # This naming in controllers/chapter.py seems confused (copy-paste error likely).
    # `instance = await self.get(novel_id)` -> implies it gets by ID.
    # Since we are testing the Controller as written:
    updated = await chapter_controller.update(chapter.id, update_data)

    assert updated.name == "Updated Name"
    assert updated.content == "New Content"

@pytest.mark.asyncio
async def test_delete_chapter():
    """Test deleting a chapter."""
    novel = await Novel.create(name="Delete Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="Delete Chapter",
        content="Content"
    )

    # CRUDBase.remove takes an object
    await chapter_controller.remove(chapter.id)

    exists = await Chapter.filter(id=chapter.id).exists()
    assert not exists
