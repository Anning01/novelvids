import pytest

from models.novel import Novel
from models.asset import Asset
from models.asset_variant import AssetVariant
from services.video.asset_resolver import resolve_assets, MENTION_PATTERN
from utils.enums import AssetTypeEnum


@pytest.mark.asyncio
async def test_解析单个资产引用():
    """@张三 解析为一个 subject。"""
    novel = await Novel.create(name="Resolver Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )

    subjects = await resolve_assets("@张三 在大殿中行走", novel.id)
    assert len(subjects) == 1
    assert subjects[0]["name"] == "张三"
    print(f"    单个资产引用: {subjects[0]['name']}")


@pytest.mark.asyncio
async def test_解析多个资产引用():
    """@张三 和 @李四 解析为两个 subject。"""
    novel = await Novel.create(name="Multi Resolver Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李四",
    )

    subjects = await resolve_assets("@张三 和 @李四 在大殿中行走", novel.id)
    assert len(subjects) == 2
    names = {s["name"] for s in subjects}
    assert "张三" in names
    assert "李四" in names
    print(f"    多个资产引用: {names}")


@pytest.mark.asyncio
async def test_通过别名解析资产():
    """@小张 通过 aliases 匹配到 张三。"""
    novel = await Novel.create(name="Alias Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
        aliases=["小张", "张大侠"],
    )

    subjects = await resolve_assets("@小张 在大殿中行走", novel.id)
    assert len(subjects) == 1
    assert subjects[0]["name"] == "张三"
    print(f"    别名解析: @小张 -> {subjects[0]['name']}")


@pytest.mark.asyncio
async def test_无引用返回空列表():
    """prompt 不含 @ 时返回空。"""
    novel = await Novel.create(name="Empty Novel", author="Author")
    subjects = await resolve_assets("在大殿中行走", novel.id)
    assert subjects == []
    print(f"    无引用: subjects={subjects}")


@pytest.mark.asyncio
async def test_未匹配资产被忽略():
    """@不存在 不在数据库中，被忽略。"""
    novel = await Novel.create(name="No Match Novel", author="Author")
    subjects = await resolve_assets("@不存在的角色 在大殿", novel.id)
    assert subjects == []
    print(f"    未匹配: subjects={subjects}")


@pytest.mark.asyncio
async def test_重复引用不重复():
    """同一个 @张三 出现两次只产生一个 subject。"""
    novel = await Novel.create(name="Dedup Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )

    subjects = await resolve_assets("@张三 走到 @张三 面前", novel.id)
    assert len(subjects) == 1
    print(f"    去重: subjects count={len(subjects)}")


@pytest.mark.asyncio
async def test_通过形态名称选择资产多图():
    novel = await Novel.create(name="Variant Resolver Novel", author="Author")
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李火旺",
        main_image="https://example.com/base.png",
    )
    await AssetVariant.create(
        asset=asset,
        name="红衣变装",
        description="红色道袍造型",
        images=[
            "https://example.com/red-front.png",
            "https://example.com/red-side.png",
        ],
    )

    subjects = await resolve_assets("@{李火旺#红衣变装} 进入大殿", novel.id)

    assert subjects == [{
        "name": "李火旺#红衣变装",
        "variant_name": "红衣变装",
        "images": [
            "https://example.com/red-front.png",
            "https://example.com/red-side.png",
        ],
        "description": "红色道袍造型",
    }]


@pytest.mark.asyncio
async def test_按章节自动采用资产升级形态():
    novel = await Novel.create(name="Chapter Variant Novel", author="Author")
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.scene.value,
        canonical_name="白玉京",
        main_image="https://example.com/base.png",
    )
    await AssetVariant.create(
        asset=asset,
        name="战后废墟",
        description="坍塌后的白玉京",
        chapter_numbers=[205],
        images=["https://example.com/ruin.png"],
    )

    subjects = await resolve_assets("@白玉京", novel.id, chapter_number=205)

    assert subjects[0]["name"] == "白玉京"
    assert subjects[0]["variant_name"] == "战后废墟"
    assert subjects[0]["images"] == ["https://example.com/ruin.png"]


def test_mention正则匹配():
    """验证 MENTION_PATTERN 能匹配中英文。"""
    text = "@张三 和 @Alice 在 @大殿 里"
    matches = [braced or plain for braced, plain in MENTION_PATTERN.findall(text)]
    assert "张三" in matches
    assert "Alice" in matches
    assert "大殿" in matches
    print(f"    正则匹配: {matches}")
