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
async def test_api_create_novel_persists_canonical_project_defaults(client: AsyncClient):
    response = await client.post(
        "/api/novel",
        json={
            "name": "Canonical Project",
            "author": "人工创建",
            "description": "人工模式",
            "aspect_ratio": "9:16",
            "resolution": "1080p",
            "style_key": "realistic-cinematic",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["workflow_kind"] == "script"
    assert body["data"]["aspect_ratio"] == "9:16"
    assert body["data"]["resolution"] == "1080p"
    assert body["data"]["style_key"] == "realistic-cinematic"
    assert body["data"]["custom_style_prompt"] is None

    novel = await Novel.get(id=body["data"]["id"])
    assert novel.aspect_ratio == "9:16"
    assert novel.resolution == "1080p"


@pytest.mark.asyncio
async def test_api_create_novel_rejects_conflicting_or_invalid_project_defaults(
    client: AsyncClient,
):
    conflicting = await client.post(
        "/api/novel",
        json={
            "name": "Conflicting Style",
            "style_key": "realistic-general",
            "custom_style_prompt": "自定义风格",
        },
    )
    invalid_ratio = await client.post(
        "/api/novel",
        json={
            "name": "Invalid Ratio",
            "aspect_ratio": "2:1",
        },
    )
    blank_custom_style = await client.post(
        "/api/novel",
        json={
            "name": "Blank Custom Style",
            "custom_style_prompt": "   ",
        },
    )

    assert conflicting.json()["code"] == 422
    assert invalid_ratio.json()["code"] == 422
    assert blank_custom_style.json()["code"] == 422
    assert await Novel.filter(
        name__in=["Conflicting Style", "Invalid Ratio", "Blank Custom Style"]
    ).count() == 0

@pytest.mark.asyncio
async def test_api_get_novel_list(client: AsyncClient):
    """Test getting novel list."""
    await Novel.create(
        name="List Novel 1",
        author="Author 1",
        cover="/media/covers/novel-1-abc.png",
    )
    await Novel.create(name="List Novel 2", author="Author 2")

    response = await client.get("/api/novel")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    items = data["items"]
    assert len(items) >= 2
    assert data["pagination"]["total"] >= 2
    first = next(item for item in items if item["name"] == "List Novel 1")
    assert first["cover"] == "/media/covers/novel-1-abc.png"
    assert first["cover_thumbnail"] == (
        "/media/covers/derivatives/novel-1-abc-thumbnail.webp"
    )
    assert first["cover_preview"] == (
        "/media/covers/derivatives/novel-1-abc-preview.webp"
    )

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
async def test_api_patch_novel_analysis_editor_fields(client: AsyncClient):
    novel = await Novel.create(name="Editable Analysis", author="Author")

    response = await client.patch(
        f"/api/novel/{novel.id}",
        json={
            "name": "新的小说昵称",
            "tags": ["都市", "成长"],
            "story_outline": "人工调整后的故事大纲。",
            "project_type": "都市精品短剧",
            "project_setting": "采用现实主义世界观。",
            "storyboard_strategy": "快节奏动作叙事",
            "storyboard_setting": "重点突出动作连续性与情绪反应。",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["name"] == "新的小说昵称"
    assert body["data"]["tags"] == ["都市", "成长"]
    assert body["data"]["story_outline"] == "人工调整后的故事大纲。"
    assert body["data"]["project_type"] == "都市精品短剧"
    assert body["data"]["project_setting"] == "采用现实主义世界观。"
    assert body["data"]["storyboard_strategy"] == "快节奏动作叙事"
    assert body["data"]["storyboard_setting"] == "重点突出动作连续性与情绪反应。"

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
    # 拆分响应不再把整份书稿正文回传（前端无需也不应拿到 content）
    assert "content" not in data


@pytest.mark.asyncio
async def test_api_create_novel_from_source_key(client: AsyncClient, monkeypatch):
    """OSS 直传后仅回传 key，服务端经内网读取并解析正文，响应不回传正文。"""
    from controllers import novel as novel_controller_module
    from services import document as document_module

    class FakeOss:
        enabled = True

        async def get_bytes(self, key):
            assert key == "uploads/0/20260818/script.txt"
            return "第1章 开端\n这是第一章正文。\n\n第2章 发展\n这是第二章正文。".encode("utf-8")

        def public_url(self, key):
            return f"https://fake-cdn/{key}"

    fake = FakeOss()
    monkeypatch.setattr(novel_controller_module, "oss", fake)
    monkeypatch.setattr(document_module, "oss", fake)

    response = await client.post(
        "/api/novel",
        json={
            "name": "OSS Novel",
            "author": "Agent 创建",
            "description": "x",
            "source_key": "uploads/0/20260818/script.txt",
            "source_filename": "script.txt",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "OSS Novel"
    assert "content" not in data

    novel = await Novel.get(id=data["id"])
    assert "这是第一章正文" in novel.content
    assert novel.total_chapters == 0  # 正文已解析入库，章节拆分由 /split 完成


@pytest.mark.asyncio
async def test_api_create_novel_source_key_invalid_rejected(client: AsyncClient, monkeypatch):
    """长书稿无章节标记时，创建阶段即拒绝，避免进入工作流后再失败。"""
    from controllers import novel as novel_controller_module
    from services import document as document_module

    class FakeOss:
        enabled = True

        async def get_bytes(self, key):
            return ("这是没有章节标题的正文。" * 3_000).encode("utf-8")

    fake = FakeOss()
    monkeypatch.setattr(novel_controller_module, "oss", fake)
    monkeypatch.setattr(document_module, "oss", fake)

    response = await client.post(
        "/api/novel",
        json={
            "name": "Invalid OSS Novel",
            "author": "Agent 创建",
            "source_key": "uploads/0/x/long.txt",
            "source_filename": "long.txt",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] != 0
    assert await Novel.filter(name="Invalid OSS Novel").count() == 0


@pytest.mark.asyncio
async def test_api_novel_meta_excludes_content(client: AsyncClient):
    """元信息接口不返回书稿正文，但给出正文字符数用于拆分校验。"""
    created = await client.post(
        "/api/novel",
        json={"name": "元信息项目", "author": "x", "content": "第一章 开端" * 100},
    )
    novel_id = created.json()["data"]["id"]

    response = await client.get(f"/api/novel/{novel_id}/meta")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert "content" not in data
    assert data["content_length"] == len("第一章 开端" * 100)
    assert data["name"] == "元信息项目"
    assert data["total_chapters"] == 0
    assert data["cover_thumbnail"] is None
    assert data["cover_preview"] is None
