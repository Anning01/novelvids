import pytest
from httpx import AsyncClient
from models.novel import Novel

@pytest.mark.asyncio
async def test_api_create_novel(client: AsyncClient):
    """Test creating a novel via API."""
    payload = {
        "name": "API Novel",
        "author": "API Author",
        "content": "API Content",
        "description": "API Desc"
    }
    response = await client.post("/api/novel", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "API Novel"
    assert "id" in data

@pytest.mark.asyncio
async def test_api_get_novel_list(client: AsyncClient):
    """Test getting novel list."""
    await Novel.create(name="List Novel 1", author="Author 1")
    await Novel.create(name="List Novel 2", author="Author 2")

    response = await client.get("/api/novel")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    items = data["items"]
    assert len(items) >= 2
    assert data["pagination"]["total"] >= 2

@pytest.mark.asyncio
async def test_api_get_novel_detail(client: AsyncClient):
    """Test getting novel detail."""
    novel = await Novel.create(name="Detail Novel", author="Author")

    response = await client.get(f"/api/novel/{novel.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == novel.id
    assert data["name"] == "Detail Novel"

@pytest.mark.asyncio
async def test_api_update_novel(client: AsyncClient):
    """Test updating a novel."""
    novel = await Novel.create(name="Old Name", author="Author")

    payload = {
        "name": "New Name",
        "author": "New Author",
        "content": "New Content"
    }

    # API fixed to PUT /api/novel/{id}
    response = await client.put(f"/api/novel/{novel.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "New Name"
    assert data["content"] == "New Content"

@pytest.mark.asyncio
async def test_api_patch_novel(client: AsyncClient):
    """Test patching a novel."""
    novel = await Novel.create(name="Patch Name", author="Author")

    payload = {
        "name": "Patched Name"
    }

    # API fixed to PATCH /api/novel/{id}
    response = await client.patch(f"/api/novel/{novel.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "Patched Name"
    # Content should remain unchanged (None or whatever default)

@pytest.mark.asyncio
async def test_api_delete_novel(client: AsyncClient):
    """Test deleting a novel."""
    novel = await Novel.create(name="Delete API", author="Author")

    response = await client.delete(f"/api/novel/{novel.id}")
    assert response.status_code == 200, response.text

    exists = await Novel.filter(id=novel.id).exists()
    assert not exists

@pytest.mark.asyncio
async def test_api_split_novel(client: AsyncClient):
    """Test splitting novel via API."""
    content = "第1章 A\nAAA\n第2章 B\nBBB"
    novel = await Novel.create(name="Split API", author="Author", content=content)

    response = await client.get(f"/api/novel/{novel.id}/split")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_chapters"] == 2
