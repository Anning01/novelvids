import pytest
from httpx import AsyncClient
from models.novel import Novel
from models.chapter import Chapter


@pytest.mark.asyncio
async def test_api_create_chapter(client: AsyncClient):
    """创建章节。"""
    novel = await Novel.create(name="API Chapter Novel", author="Author")
    payload = {
        "number": 1,
        "name": "API Chapter",
        "content": "Content",
        "novel_id": novel.id,
    }

    response = await client.post("/api/chapter", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "API Chapter"
    assert data["id"] is not None


@pytest.mark.asyncio
async def test_api_get_chapter_detail(client: AsyncClient):
    """获取章节详情。"""
    novel = await Novel.create(name="Detail Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Detail Chapter", content="Content"
    )

    response = await client.get(f"/api/chapter/{chapter.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == chapter.id
    assert data["name"] == "Detail Chapter"


@pytest.mark.asyncio
async def test_api_update_chapter(client: AsyncClient):
    """全量更新章节。"""
    novel = await Novel.create(name="Update Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Old Name", content="Old Content"
    )

    payload = {
        "number": 1,
        "name": "Updated Name",
        "content": "New Content",
        "novel_id": novel.id,
    }

    response = await client.put(f"/api/chapter/{chapter.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Updated Name"
    assert data["content"] == "New Content"


@pytest.mark.asyncio
async def test_api_patch_chapter(client: AsyncClient):
    """局部更新章节。"""
    novel = await Novel.create(name="Patch Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Original Name", content="Original Content"
    )

    response = await client.patch(
        f"/api/chapter/{chapter.id}",
        json={"name": "Patched Name"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Patched Name"
    assert data["content"] == "Original Content"  # 未改动


@pytest.mark.asyncio
async def test_api_get_chapter_list(client: AsyncClient):
    """获取章节列表。"""
    novel = await Novel.create(name="List Chapter Novel", author="Author")
    await Chapter.create(novel_id=novel.id, number=1, name="Ch1", content="C1")
    await Chapter.create(novel_id=novel.id, number=2, name="Ch2", content="C2")

    response = await client.get("/api/chapter")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pagination"]["total"] >= 2


@pytest.mark.asyncio
async def test_api_delete_chapter(client: AsyncClient):
    """删除章节。"""
    novel = await Novel.create(name="Delete Chapter Novel", author="Author")
    chapter = await Chapter.create(
        novel_id=novel.id, number=1, name="Delete Chapter", content="Content"
    )

    response = await client.delete(f"/api/chapter/{chapter.id}")
    assert response.status_code == 200, response.text

    exists = await Chapter.filter(id=chapter.id).exists()
    assert not exists
