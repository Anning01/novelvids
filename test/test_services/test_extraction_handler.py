import asyncio
from unittest.mock import patch, AsyncMock

import pytest

from models.novel import Novel
from models.chapter import Chapter
from models.asset import Asset
from models.config import AiModelConfig
from services.extraction.handler import ExtractionTaskHandler
from services.extraction.extractor import (
    PersonList, SceneList, ItemList,
    Person, Scene, Item,
)
from utils.enums import AiTaskTypeEnum, AssetTypeEnum


# ---- Mock 数据 ----

MOCK_PERSONS = PersonList(persons=[
    Person(
        name="张三",
        aliases=["小张", "张哥"],
        description="主角，沉稳冷静",
        base_traits="young man, calm expression, black hair",
        appearances=[],
    ),
    Person(
        name="李四",
        aliases=["老李"],
        description="反派角色",
        base_traits="tall man, sharp eyes, scar on cheek",
        appearances=[],
    ),
])

MOCK_SCENES = SceneList(scenes=[
    Scene(
        name="皇宫大殿",
        aliases=["金銮殿"],
        description="辉煌壮丽的大殿",
        base_traits="grand palace hall, golden pillars",
        appearances=[],
    ),
])

MOCK_ITEMS = ItemList(items=[
    Item(
        name="尚方宝剑",
        aliases=["天子剑"],
        description="御赐宝剑",
        base_traits="golden sword with dragon engravings",
        appearances=[],
    ),
])

MOCK_EMPTY_PERSONS = PersonList(persons=[])
MOCK_EMPTY_SCENES = SceneList(scenes=[])
MOCK_EMPTY_ITEMS = ItemList(items=[])


async def _mock_extract(self, text, chapter_number):
    """根据提取器类型返回对应的 mock 数据。"""
    if self.response_model == PersonList:
        return MOCK_PERSONS
    elif self.response_model == SceneList:
        return MOCK_SCENES
    elif self.response_model == ItemList:
        return MOCK_ITEMS


async def _mock_extract_empty(self, text, chapter_number):
    """返回空结果的 mock。"""
    if self.response_model == PersonList:
        return MOCK_EMPTY_PERSONS
    elif self.response_model == SceneList:
        return MOCK_EMPTY_SCENES
    elif self.response_model == ItemList:
        return MOCK_EMPTY_ITEMS


async def _setup_env():
    """创建测试环境：小说 + 章节。"""
    novel = await Novel.create(name="提取测试小说", author="测试作者")
    chapter = await Chapter.create(
        novel_id=novel.id,
        number=1,
        name="第1章",
        content="张三走进了皇宫大殿，手持尚方宝剑。李四阴沉地站在一旁。",
    )
    return novel, chapter


# =====================================================================
# 正常提取
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_正常提取_写入所有类型资产():
    """提取人物/场景/物品并写入 Asset 表。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    result = await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 3,
    })

    # 验证返回摘要
    assert len(result["persons"]) == 2
    assert len(result["scenes"]) == 1
    assert len(result["items"]) == 1
    assert all(p["action"] == "created" for p in result["persons"])

    # 验证数据库
    persons = await Asset.filter(
        novel_id=novel.id, asset_type=AssetTypeEnum.person.value
    )
    assert len(persons) == 2
    assert {p.canonical_name for p in persons} == {"张三", "李四"}
    assert {p.metadata["reference_layout"] for p in persons} == {
        "character_turnaround"
    }

    scenes = await Asset.filter(
        novel_id=novel.id, asset_type=AssetTypeEnum.scene.value
    )
    assert len(scenes) == 1
    assert scenes[0].canonical_name == "皇宫大殿"

    items = await Asset.filter(
        novel_id=novel.id, asset_type=AssetTypeEnum.item.value
    )
    assert len(items) == 1


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_正常提取_source_chapters记录章节号():
    """提取后 Asset 的 source_chapters 包含章节号。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    person = await Asset.get(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    assert 1 in person.source_chapters
    assert person.last_updated_chapter == 1


# =====================================================================
# 增量合并
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_增量提取_合并别名和章节():
    """第二次提取同名资产时，合并别名并追加章节号。"""
    novel, chapter1 = await _setup_env()
    handler = ExtractionTaskHandler()

    # 第一次提取（第1章）
    await handler.execute({
        "chapter_id": chapter1.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    # 创建第二章
    chapter2 = await Chapter.create(
        novel_id=novel.id,
        number=2,
        name="第2章",
        content="张三再次出现。",
    )

    # 第二次提取（第2章）
    result = await handler.execute({
        "chapter_id": chapter2.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    # 应该是 updated 而不是 created
    person_actions = {p["name"]: p["action"] for p in result["persons"]}
    assert person_actions["张三"] == "updated"

    # 数据库中张三只有一条记录
    persons = await Asset.filter(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    assert len(persons) == 1

    person = persons[0]
    assert 1 in person.source_chapters
    assert 2 in person.source_chapters
    assert person.last_updated_chapter == 2


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_增量提取_同一章节重复提取不重复追加():
    """对同一章节重复提取，source_chapters 不会重复添加章节号。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    # 提取两次
    await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })
    await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    person = await Asset.get(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    # chapter 1 只应出现一次
    assert person.source_chapters.count(1) == 1


@pytest.mark.asyncio
async def test_增量提取_别名命中且空字段不覆盖旧资料():
    novel = await Novel.create(name="别名合并小说")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李火旺",
        aliases=["红中"],
        description="保留的旧描述",
        base_traits="保留的旧视觉资料",
        main_image="/media/li-huowang.png",
        source_chapters=[1],
        last_updated_chapter=1,
    )
    handler = ExtractionTaskHandler()
    alias_person = Person(
        name="红中",
        aliases=["李兄"],
        description="",
        base_traits="",
        appearances=[],
    )

    result = await handler._save_assets(
        novel.id,
        9,
        AssetTypeEnum.person,
        [alias_person],
    )
    await existing.refresh_from_db()

    assert result == [{"name": "红中", "action": "updated"}]
    assert await Asset.filter(novel=novel).count() == 1
    assert existing.description == "保留的旧描述"
    assert existing.base_traits == "保留的旧视觉资料"
    assert existing.main_image == "/media/li-huowang.png"
    assert existing.source_chapters == [1, 9]
    assert set(existing.aliases) == {"红中", "李兄"}


@pytest.mark.asyncio
async def test_增量提取_较早章节重跑不会回滚较新资料():
    novel = await Novel.create(name="状态机防回滚")
    existing = await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.item.value,
        canonical_name="桃木牌",
        aliases=["洞窟铭牌"],
        description="第八十八章确认的完整新资料",
        base_traits="完整的新形态",
        source_chapters=[88],
        last_updated_chapter=88,
    )
    handler = ExtractionTaskHandler()
    older_item = Item(
        name="洞窟铭牌",
        aliases=[],
        description="第一章的早期旧资料",
        base_traits="旧形态",
        appearances=[],
    )

    await handler._save_assets(
        novel.id,
        1,
        AssetTypeEnum.item,
        [older_item],
    )
    await existing.refresh_from_db()

    assert existing.description == "第八十八章确认的完整新资料"
    assert existing.base_traits == "完整的新形态"
    assert existing.source_chapters == [1, 88]
    assert existing.last_updated_chapter == 88


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_增量提取_合并别名去重():
    """合并别名时应去重。"""
    novel, chapter1 = await _setup_env()
    handler = ExtractionTaskHandler()

    # 第一次提取
    await handler.execute({
        "chapter_id": chapter1.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    # 第二次提取（返回相同别名）
    chapter2 = await Chapter.create(
        novel_id=novel.id, number=2, name="第2章", content="重复内容",
    )
    await handler.execute({
        "chapter_id": chapter2.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    person = await Asset.get(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    # aliases 应该去重：["小张", "张哥"]
    assert len(person.aliases) == len(set(person.aliases))


# =====================================================================
# 空结果
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract_empty,
)
async def test_空提取结果_不写入任何资产():
    """LLM 返回空结果时不应创建任何 Asset。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    result = await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    assert result["persons"] == []
    assert result["scenes"] == []
    assert result["items"] == []

    count = await Asset.filter(novel_id=novel.id).count()
    assert count == 0


# =====================================================================
# 异常场景
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    side_effect=Exception("LLM 接口调用失败"),
)
async def test_提取异常_抛出到上层(mock_extract):
    """LLM 调用失败时应向上抛出异常，由 executor 处理。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    with pytest.raises(Exception, match="LLM 接口调用失败"):
        await handler.execute({
            "chapter_id": chapter.id,
            "novel_id": novel.id,
            "base_url": "https://mock.com",
            "api_key": "sk-mock",
            "model": "mock-model",
            "concurrency": 1,
        })


# =====================================================================
# 并发控制
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_并发数为1时串行提取():
    """concurrency=1 时三个提取器应串行运行。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    result = await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    })

    # 只要结果完整即可（串行也能完成）
    assert len(result["persons"]) == 2
    assert len(result["scenes"]) == 1
    assert len(result["items"]) == 1


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_并发数为3时并行提取():
    """concurrency=3 时三个提取器可以全部并行。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    result = await handler.execute({
        "chapter_id": chapter.id,
        "novel_id": novel.id,
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 3,
    })

    assert len(result["persons"]) == 2
    assert len(result["scenes"]) == 1
    assert len(result["items"]) == 1


# =====================================================================
# 多小说隔离
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.BaseExtractor.extract",
    new=_mock_extract,
)
async def test_不同小说的资产互相隔离():
    """两本小说提取相同名称的角色，不应合并。"""
    novel1 = await Novel.create(name="小说A", author="作者A")
    novel2 = await Novel.create(name="小说B", author="作者B")
    ch1 = await Chapter.create(
        novel_id=novel1.id, number=1, name="A-Ch1", content="内容A"
    )
    ch2 = await Chapter.create(
        novel_id=novel2.id, number=1, name="B-Ch1", content="内容B"
    )

    handler = ExtractionTaskHandler()
    params_base = {
        "base_url": "https://mock.com",
        "api_key": "sk-mock",
        "model": "mock-model",
        "concurrency": 1,
    }

    await handler.execute({
        **params_base, "chapter_id": ch1.id, "novel_id": novel1.id,
    })
    await handler.execute({
        **params_base, "chapter_id": ch2.id, "novel_id": novel2.id,
    })

    # 两本小说各有自己的张三
    p1 = await Asset.filter(
        novel_id=novel1.id, asset_type=AssetTypeEnum.person.value, canonical_name="张三"
    )
    p2 = await Asset.filter(
        novel_id=novel2.id, asset_type=AssetTypeEnum.person.value, canonical_name="张三"
    )
    assert len(p1) == 1
    assert len(p2) == 1
    assert p1[0].id != p2[0].id
