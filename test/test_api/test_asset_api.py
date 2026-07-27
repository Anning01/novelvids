import pytest
from httpx import AsyncClient
from models.novel import Novel
from models.asset import Asset
from models.chapter import Chapter
from utils.enums import AssetTypeEnum


@pytest.mark.asyncio
async def test_api_create_asset(client: AsyncClient):
    """创建资产。"""
    novel = await Novel.create(name="Asset Novel", author="Author")
    payload = {
        "asset_type": AssetTypeEnum.person.value,
        "novel_id": novel.id,
        "canonical_name": "张三",
        "aliases": ["小张", "张哥"],
        "description": "主角，性格沉稳",
        "base_traits": "young man, calm expression",
    }
    response = await client.post("/api/asset", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["canonical_name"] == "张三"
    assert data["asset_type"] == AssetTypeEnum.person.value


@pytest.mark.asyncio
async def test_api_create_product_asset(client: AsyncClient):
    """商品资产使用稳定的扩展枚举值。"""
    novel = await Novel.create(name="Product Asset Novel", author="Author")

    response = await client.post(
        "/api/asset",
        json={
            "novel_id": novel.id,
            "asset_type": 4,
            "canonical_name": "示例商品",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["asset_type"] == 4


@pytest.mark.asyncio
async def test_api_get_asset_list(client: AsyncClient):
    """获取资产列表。"""
    novel = await Novel.create(name="List Asset Novel", author="Author")
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="人物A",
    )
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="场景A",
    )

    response = await client.get("/api/asset")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pagination"]["total"] >= 2


@pytest.mark.asyncio
async def test_api_get_asset_detail(client: AsyncClient):
    """获取资产详情。"""
    novel = await Novel.create(name="Detail Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="宝剑",
        description="削铁如泥的宝剑",
        base_traits="a shining sword with golden handle",
    )

    response = await client.get(f"/api/asset/{asset.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == asset.id
    assert data["canonical_name"] == "宝剑"


@pytest.mark.asyncio
async def test_api_asset_variants_support_multiple_images(client: AsyncClient):
    """同一资产可以保存人物变装、场景升级或道具形态的多张参考图。"""
    novel = await Novel.create(name="Variant Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李火旺",
    )

    response = await client.post(
        f"/api/asset/{asset.id}/variants",
        json={
            "name": "红衣变装",
            "description": "进入后期后的红色道袍造型",
            "chapter_numbers": [101, 102, 103],
            "images": ["/media/a.png", "/media/b.png", "/media/c.png"],
        },
    )

    assert response.status_code == 200, response.text
    variant = response.json()["data"]
    assert variant["asset_id"] == asset.id
    assert variant["images"] == ["/media/a.png", "/media/b.png", "/media/c.png"]

    detail = await client.get(f"/api/asset/{asset.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["variants"][0]["name"] == "红衣变装"


@pytest.mark.asyncio
async def test_api_reuse_asset_in_chapter_is_idempotent(client: AsyncClient):
    """复用项目资产只追加章节关联，重复操作不会复制资产或章节号。"""
    novel = await Novel.create(name="Reusable Asset Novel", author="Author")
    first_chapter = await Chapter.create(
        novel=novel,
        number=1,
        name="第一章",
        content="第一章内容",
    )
    second_chapter = await Chapter.create(
        novel=novel,
        number=205,
        name="第二百零五章",
        content="第二百零五章内容",
    )
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李火旺",
        source_chapters=[first_chapter.number],
        last_updated_chapter=first_chapter.number,
    )

    first_response = await client.post(
        f"/api/asset/{asset.id}/chapters/{second_chapter.id}"
    )
    second_response = await client.post(
        f"/api/asset/{asset.id}/chapters/{second_chapter.id}"
    )

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    assert second_response.json()["data"]["source_chapters"] == [1, 205]
    assert await Asset.filter(novel=novel, canonical_name="李火旺").count() == 1


@pytest.mark.asyncio
async def test_api_reuse_asset_rejects_cross_project_chapter(client: AsyncClient):
    """资产不能复用到其他项目的章节。"""
    source_novel = await Novel.create(name="Source Novel", author="Author")
    target_novel = await Novel.create(name="Target Novel", author="Author")
    target_chapter = await Chapter.create(
        novel=target_novel,
        number=1,
        name="目标章节",
        content="目标章节内容",
    )
    asset = await Asset.create(
        novel=source_novel,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="白玉京",
    )

    response = await client.post(
        f"/api/asset/{asset.id}/chapters/{target_chapter.id}"
    )

    assert response.status_code == 200, response.text
    assert response.json()["code"] == 400
    await asset.refresh_from_db()
    assert asset.source_chapters == []


@pytest.mark.asyncio
async def test_api_update_asset(client: AsyncClient):
    """全量更新资产。"""
    novel = await Novel.create(name="Update Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="旧名",
    )

    payload = {
        "asset_type": AssetTypeEnum.person.value,
        "novel_id": novel.id,
        "canonical_name": "新名",
        "description": "更新后的描述",
    }
    response = await client.put(f"/api/asset/{asset.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["canonical_name"] == "新名"


@pytest.mark.asyncio
async def test_api_patch_asset(client: AsyncClient):
    """局部更新资产。"""
    novel = await Novel.create(name="Patch Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="Patch Name",
        description="原始描述",
    )

    response = await client.patch(
        f"/api/asset/{asset.id}",
        json={"description": "新描述"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["description"] == "新描述"
    assert data["canonical_name"] == "Patch Name"  # 未改动


@pytest.mark.asyncio
async def test_api_get_asset_list_with_invalid_chapter_filter(client: AsyncClient):
    """chapter_id 无效时忽略过滤，正常返回列表。"""
    novel = await Novel.create(name="Filter Asset Novel", author="Author")
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="过滤测试",
    )

    # 传入无效 chapter_id，应被忽略，正常返回
    response = await client.get("/api/asset?chapter_id=abc")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pagination"]["total"] >= 1


@pytest.mark.asyncio
async def test_api_delete_asset(client: AsyncClient):
    """删除资产。"""
    novel = await Novel.create(name="Delete Asset Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="待删除",
    )

    response = await client.delete(f"/api/asset/{asset.id}")
    assert response.status_code == 200, response.text

    exists = await Asset.filter(id=asset.id).exists()
    assert not exists


@pytest.mark.asyncio
async def test_api_reference_asset(client: AsyncClient):
    """提交参考图生成任务。"""
    from models.config import AiModelConfig
    from models.ai_task import AiTask
    from utils.enums import AiTaskTypeEnum, TaskStatusEnum

    novel = await Novel.create(name="Ref API Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="API参考图测试",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="test-ref-api",
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )

    response = await client.get(f"/api/asset/reference/{asset.id}")
    assert response.status_code == 200, response.text

    data = response.json()["data"]
    assert data["task_type"] == AiTaskTypeEnum.reference_image.value
    assert data["status"] == TaskStatusEnum.pending.value
    print(f"    GET /api/asset/reference/{asset.id} -> 200, 任务 id={data['id']}, status=pending")


@pytest.mark.asyncio
async def test_api_reference_no_config(client: AsyncClient):
    """无参考图配置时返回 404。"""
    novel = await Novel.create(name="No Config Ref API Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="API无配置测试",
    )

    response = await client.get(f"/api/asset/reference/{asset.id}")
    body = response.json()
    assert body["code"] == 404
    print(f"    GET /api/asset/reference/{asset.id} -> 404: {body['message']}")
