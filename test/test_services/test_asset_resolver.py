import pytest

from models.novel import Novel
from models.asset import Asset
from models.asset_variant import AssetVariant
from services.video.asset_resolver import (
    MENTION_PATTERN,
    normalize_selected_variant_ids,
    resolve_assets,
)
from services.video.seedance import SeedanceGenerator
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


@pytest.mark.asyncio
async def test_分镜显式选择的资产形态优先于章节默认形态():
    novel = await Novel.create(name="Explicit Variant Novel", author="Author")
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="艾伦",
        main_image="https://example.com/base.png",
    )
    chapter_variant = await AssetVariant.create(
        asset=asset,
        name="冬季披风",
        chapter_numbers=[5],
        images=["https://example.com/winter.png"],
    )
    selected_variant = await AssetVariant.create(
        asset=asset,
        name="负伤便装",
        images=["https://example.com/injured.png"],
    )

    subjects = await resolve_assets(
        "@艾伦 穿过街道",
        novel.id,
        chapter_number=5,
        selected_asset_ids=[asset.id],
        selected_variant_ids={asset.id: selected_variant.id},
    )

    assert chapter_variant.id != selected_variant.id
    assert subjects[0]["variant_name"] == "负伤便装"
    assert subjects[0]["images"] == ["https://example.com/injured.png"]


@pytest.mark.asyncio
async def test_分镜绑定但提示词未引用的资产不会作为参考素材():
    novel = await Novel.create(name="Bound Asset Novel", author="Author")
    asset = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="长剑",
        main_image="https://example.com/sword.png",
    )

    subjects = await resolve_assets(
        "雨夜中的决斗",
        novel.id,
        selected_asset_ids=[asset.id],
        selected_variant_ids={asset.id: None},
    )

    assert subjects == []


@pytest.mark.asyncio
async def test_提示词引用未绑定到分镜的资产不会越权提交():
    novel = await Novel.create(name="Unbound Asset Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="路人",
        main_image="https://example.com/person.png",
    )

    subjects = await resolve_assets("@路人 走入画面", novel.id, selected_asset_ids=[])

    assert subjects == []


def test_标准化分镜资产形态映射():
    assert normalize_selected_variant_ids({"1": 11, 2: None, "bad": 3, "4": -1}) == {
        1: 11,
        2: None,
    }


@pytest.mark.asyncio
async def test_多图资产默认只采用当前主图():
    novel = await Novel.create(name="Primary Image Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="女主",
        main_image="https://example.com/main.png",
        angle_image_1="https://example.com/side.png",
        metadata={
            "image_gallery": [
                "https://example.com/main.png",
                "https://example.com/side.png",
                "https://example.com/back.png",
            ],
        },
    )

    subjects = await resolve_assets("@女主 走入画面", novel.id)

    assert subjects[0]["images"] == ["https://example.com/main.png"]


@pytest.mark.asyncio
async def test_多图资产采用显式选择的图片():
    novel = await Novel.create(name="Selected Images Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.product.value,
        canonical_name="面膜",
        main_image="https://example.com/front.png",
        angle_image_1="https://example.com/side.png",
        metadata={
            "image_gallery": [
                "https://example.com/front.png",
                "https://example.com/side.png",
                "https://example.com/back.png",
            ],
            "selected_image_urls": [
                "https://example.com/side.png",
                "https://example.com/back.png",
            ],
        },
    )

    subjects = await resolve_assets("@面膜 产品特写", novel.id)

    assert subjects[0]["images"] == [
        "https://example.com/side.png",
        "https://example.com/back.png",
    ]


def test_mention正则匹配():
    """验证 MENTION_PATTERN 能匹配中英文。"""
    text = "@张三 和 @Alice 在 @大殿 里"
    matches = [braced or plain for braced, plain in MENTION_PATTERN.findall(text)]
    assert "张三" in matches
    assert "Alice" in matches
    assert "大殿" in matches
    print(f"    正则匹配: {matches}")


def test_seedance_传递资产显式选择的多张图片():
    prompt, images = SeedanceGenerator._process_prompt(
        "@面膜 产品特写",
        [{
            "name": "面膜",
            "images": [
                "https://example.com/front.png",
                "https://example.com/side.png",
            ],
            "description": "白色面膜包装",
        }],
    )

    assert prompt == "[图1] 产品特写"
    assert images == [
        "https://example.com/front.png",
        "https://example.com/side.png",
    ]
