import asyncio
import logging
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from models.novel import Novel
from models.chapter import Chapter
from models.asset import Asset
from models.config import AiModelConfig
from services.extraction.budget import ContextBudgetExceededError
from services.extraction.handler import ExtractionTaskHandler
from services.extraction.extractor import (
    AssetExtractionGatewayError,
    AssetExtractionResult,
    Item,
    ItemList,
    Person,
    PersonList,
    Scene,
    SceneList,
)
from utils.enums import AiTaskTypeEnum, AssetTypeEnum


# ---- Mock 数据 ----

ZHANG_SAN_TRAITS = """时代基底: modern
国家/朝代: China
人种: Chinese
类型基底: realistic
脸型: oval face, calm dark eyes
发型: short black hair
耳饰: does not wear earrings
身材: medium height, lean build
头身比: realistic seven-and-a-half-head proportion
上身着装: charcoal cotton jacket
下身着装: straight black trousers
鞋子: brown leather shoes
性别: male
年龄: young adult"""

LI_SI_TRAITS = """时代基底: modern
国家/朝代: China
人种: Chinese
类型基底: realistic
脸型: angular face, sharp eyes, stable cheek scar
发型: short dark hair
耳饰: does not wear earrings
身材: tall, broad-shouldered build
头身比: realistic eight-head proportion
上身着装: fitted black wool coat
下身着装: dark straight trousers
鞋子: black leather boots
性别: male
年龄: middle-aged"""

MOCK_PERSONS = PersonList(persons=[
    Person(
        name="张三",
        aliases=["小张", "张哥"],
        description="主角，沉稳冷静",
        base_traits=ZHANG_SAN_TRAITS,
        appearances=[],
    ),
    Person(
        name="李四",
        aliases=["老李"],
        description="反派角色",
        base_traits=LI_SI_TRAITS,
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


async def _mock_extract(self, messages):
    """返回统一的三类资产测试数据。"""
    if self.response_model == AssetExtractionResult:
        return AssetExtractionResult(
            persons=MOCK_PERSONS.persons,
            scenes=MOCK_SCENES.scenes,
            items=MOCK_ITEMS.items,
        )
    if self.response_model == PersonList:
        return MOCK_PERSONS
    elif self.response_model == SceneList:
        return MOCK_SCENES
    elif self.response_model == ItemList:
        return MOCK_ITEMS


async def _mock_extract_empty(self, messages):
    """返回空结果的 mock。"""
    if self.response_model == AssetExtractionResult:
        return AssetExtractionResult(persons=[], scenes=[], items=[])
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


def _orchestration_case(*, assets=("known-asset",)):
    messages = [
        {"role": "system", "content": "rules-marker"},
        {"role": "user", "content": "novel-marker"},
        {"role": "user", "content": "assets-marker"},
        {"role": "user", "content": "private-chapter-marker"},
    ]
    context = SimpleNamespace(
        assets=assets,
        chapter=SimpleNamespace(number=3, content="private-chapter-marker"),
    )
    extraction_result = AssetExtractionResult(persons=[], scenes=[], items=[])
    summary = {"persons": [], "scenes": [], "items": []}
    report = SimpleNamespace(
        message_characters=(12, 12, 13, 22),
        total_characters=59,
    )
    context_loader = SimpleNamespace(load=AsyncMock(return_value=context))
    message_builder = SimpleNamespace(build=Mock(return_value=messages))
    budget_policy = SimpleNamespace(validate=Mock(return_value=report))
    budget_policy_factory = Mock(return_value=budget_policy)
    extractor = SimpleNamespace(extract=AsyncMock(return_value=extraction_result))
    extractor_factory = Mock(return_value=extractor)
    prepared_result = extraction_result.model_copy()
    prompt_preparer = SimpleNamespace(
        prepare=Mock(return_value=prepared_result),
    )
    upsert_service = SimpleNamespace(save_result=AsyncMock(return_value=summary))
    handler = ExtractionTaskHandler(
        context_loader=context_loader,
        message_builder=message_builder,
        upsert_service=upsert_service,
        prompt_preparer=prompt_preparer,
        budget_policy_factory=budget_policy_factory,
        extractor_factory=extractor_factory,
    )
    request_params = {
        "chapter_id": 31,
        "novel_id": 17,
        "base_url": "https://mock.com",
        "api_key": "secret-api-key-marker",
        "model": "mock-model",
        "prompt_language": "zh",
        "supports_json_output": True,
        "max_context_characters": 120000,
    }
    return SimpleNamespace(
        handler=handler,
        request_params=request_params,
        messages=messages,
        context=context,
        extraction_result=extraction_result,
        summary=summary,
        context_loader=context_loader,
        message_builder=message_builder,
        budget_policy=budget_policy,
        budget_policy_factory=budget_policy_factory,
        extractor=extractor,
        extractor_factory=extractor_factory,
        prepared_result=prepared_result,
        prompt_preparer=prompt_preparer,
        upsert_service=upsert_service,
    )


@pytest.mark.asyncio
async def test_handler_orchestrates_injected_collaborators_once(caplog):
    case = _orchestration_case()
    llm_client = SimpleNamespace()

    with (
        patch("services.extraction.handler.AsyncOpenAI", return_value=llm_client),
        caplog.at_level(logging.INFO, logger="services.extraction.handler"),
    ):
        summary = await case.handler.execute(case.request_params)

    assert summary == {**case.summary, "token_usage": {}}
    case.context_loader.load.assert_awaited_once_with(
        novel_id=case.request_params["novel_id"],
        chapter_id=case.request_params["chapter_id"],
    )
    case.message_builder.build.assert_called_once_with(
        case.context,
        prompt_language="zh",
    )
    case.budget_policy_factory.assert_called_once_with(120000)
    case.budget_policy.validate.assert_called_once_with(
        case.messages,
        asset_count=len(case.context.assets),
        chapter_characters=len(case.context.chapter.content),
    )
    case.extractor_factory.assert_called_once_with(
        llm_client,
        model="mock-model",
        supports_json_output=True,
    )
    case.extractor.extract.assert_awaited_once_with(case.messages)
    case.prompt_preparer.prepare.assert_called_once_with(
        case.extraction_result,
        prompt_language="zh",
    )
    case.upsert_service.save_result.assert_awaited_once_with(
        novel_id=case.request_params["novel_id"],
        chapter_number=case.context.chapter.number,
        result=case.prepared_result,
    )
    assert "assets=1" in caplog.text
    assert "message_chars=(12, 12, 13, 22)" in caplog.text
    assert (
        "roles=(system,user,user,user) call_status=started" in caplog.text
    )
    assert (
        "roles=(system,user,user,user) call_status=succeeded" in caplog.text
    )
    assert "call_status=failed" not in caplog.text
    assert "private-chapter-marker" not in caplog.text
    assert "secret-api-key-marker" not in caplog.text


@pytest.mark.asyncio
async def test_handler_budget_failure_stops_model_and_persistence():
    case = _orchestration_case()
    case.budget_policy.validate.side_effect = ContextBudgetExceededError(
        "资产上下文超限"
    )

    with pytest.raises(ContextBudgetExceededError, match="资产上下文超限"):
        await case.handler.execute(case.request_params)

    case.extractor_factory.assert_not_called()
    case.extractor.extract.assert_not_awaited()
    case.upsert_service.save_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_maps_injected_extractor_failure_without_logging_content(
    caplog,
):
    case = _orchestration_case()
    marker = "secret-schema-marker"
    case.extractor.extract.side_effect = ValueError(marker)

    with caplog.at_level(logging.INFO, logger="services.extraction.handler"):
        with pytest.raises(AssetExtractionGatewayError) as captured:
            await case.handler.execute(case.request_params)

    case.extractor.extract.assert_awaited_once_with(case.messages)
    case.upsert_service.save_result.assert_not_awaited()
    assert str(captured.value) == (
        "资产提取模型调用失败"
        "（错误代码：asset_extraction_gateway_error）"
    )
    assert captured.value.__suppress_context__ is True
    assert marker not in repr(captured.value)
    assert "roles=(system,user,user,user) call_status=started" in caplog.text
    assert "roles=(system,user,user,user) call_status=failed" in caplog.text
    assert "error_type=ValueError error_code=unexpected_error" in caplog.text
    assert "call_status=succeeded" not in caplog.text
    assert marker not in caplog.text


@pytest.mark.asyncio
async def test_handler_suppresses_existing_gateway_error_context(caplog):
    case = _orchestration_case()
    marker = "PRIVATE-PROVIDER-CONTEXT-MARKER"
    raised_errors = []

    async def raise_gateway_error_with_provider_context(messages):
        try:
            raise RuntimeError(marker)
        except RuntimeError:
            error = AssetExtractionGatewayError()
            raised_errors.append(error)
            raise error

    case.extractor.extract.side_effect = (
        raise_gateway_error_with_provider_context
    )

    with caplog.at_level(logging.INFO, logger="services.extraction.handler"):
        with pytest.raises(AssetExtractionGatewayError) as captured:
            await case.handler.execute(case.request_params)

    assert captured.value is raised_errors[0]
    assert captured.value.__suppress_context__ is True
    assert marker not in "".join(traceback.format_exception(captured.value))
    assert marker not in caplog.text
    case.upsert_service.save_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_preserves_extractor_cancellation():
    case = _orchestration_case()
    case.extractor.extract.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await case.handler.execute(case.request_params)

    case.upsert_service.save_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_rejects_unexpected_message_roles_before_model_call(caplog):
    case = _orchestration_case()
    case.messages[1]["role"] = "assistant"

    with caplog.at_level(logging.INFO, logger="services.extraction.handler"):
        with pytest.raises(AssetExtractionGatewayError):
            await case.handler.execute(case.request_params)

    case.extractor_factory.assert_not_called()
    case.extractor.extract.assert_not_awaited()
    case.upsert_service.save_result.assert_not_awaited()
    assert "roles=(system,assistant,user,user) call_status=failed" in caplog.text
    assert "error_code=asset_extraction_message_protocol_error" in caplog.text
    assert "private-chapter-marker" not in caplog.text
    assert "secret-api-key-marker" not in caplog.text


@pytest.mark.asyncio
async def test_handler_context_failure_stops_following_collaborators():
    case = _orchestration_case()
    case.context_loader.load.side_effect = ValueError("章节不属于小说")

    with pytest.raises(ValueError, match="不属于小说"):
        await case.handler.execute(case.request_params)

    case.message_builder.build.assert_not_called()
    case.budget_policy_factory.assert_not_called()
    case.extractor_factory.assert_not_called()
    case.extractor.extract.assert_not_awaited()
    case.upsert_service.save_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_empty_asset_registry_still_calls_model_once():
    case = _orchestration_case(assets=())

    summary = await case.handler.execute(case.request_params)

    assert summary == {**case.summary, "token_usage": {}}
    case.budget_policy.validate.assert_called_once_with(
        case.messages,
        asset_count=0,
        chapter_characters=len(case.context.chapter.content),
    )
    case.extractor.extract.assert_awaited_once_with(case.messages)
    case.upsert_service.save_result.assert_awaited_once()


# =====================================================================
# 正常提取
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.AssetExtractor.extract",
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
async def test_统一提取只请求模型一次():
    novel, chapter = await _setup_env()
    await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="宫平",
        aliases=["宫先生"],
        description="公司老实员工，遭雷劈后获得看见运势的能力。",
        base_traits="二十多岁的青年，衣着朴素，性格温和。",
        source_chapters=[99],
        metadata={"analysis_source": "project_analysis"},
    )
    result = AssetExtractionResult(
        persons=MOCK_PERSONS.persons,
        scenes=MOCK_SCENES.scenes,
        items=MOCK_ITEMS.items,
    )

    with patch(
        "services.extraction.extractor.AssetExtractor.extract",
        new=AsyncMock(return_value=result),
    ) as extract:
        await ExtractionTaskHandler().execute({
            "chapter_id": chapter.id,
            "novel_id": novel.id,
            "base_url": "https://mock.com",
            "api_key": "sk-mock",
            "model": "mock-model",
            "concurrency": 3,
            "prompt_language": "zh",
        })

    extract.assert_awaited_once()
    messages = extract.await_args.args[0]
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "user",
        "user",
    ]
    assert "宫平" in messages[2]["content"]
    assert "公司老实员工，遭雷劈后获得看见运势的能力。" in messages[2]["content"]
    assert "二十多岁的青年，衣着朴素，性格温和。" in messages[2]["content"]
    assert chapter.content in messages[3]["content"]


@pytest.mark.asyncio
async def test_Handler只委托资产保存阶段():
    novel, chapter = await _setup_env()
    extraction_result = AssetExtractionResult(
        persons=MOCK_PERSONS.persons,
        scenes=MOCK_SCENES.scenes,
        items=MOCK_ITEMS.items,
    )
    expected_summary = {
        "persons": [{"name": "张三", "action": "created"}],
        "scenes": [],
        "items": [],
    }
    prepared_result = extraction_result.model_copy()

    with (
        patch(
            "services.extraction.extractor.AssetExtractor.extract",
            new=AsyncMock(return_value=extraction_result),
        ),
        patch("services.extraction.handler.AssetUpsertService") as service_type,
        patch(
            "services.extraction.handler.AssetPromptPreparationService"
        ) as preparer_type,
    ):
        preparer_type.return_value.prepare.return_value = prepared_result
        service_type.return_value.save_result = AsyncMock(
            return_value=expected_summary
        )
        summary = await ExtractionTaskHandler().execute({
            "chapter_id": chapter.id,
            "novel_id": novel.id,
            "base_url": "https://mock.com",
            "api_key": "sk-mock",
            "model": "mock-model",
        })

    assert summary == {**expected_summary, "token_usage": {}}
    service_type.return_value.save_result.assert_awaited_once_with(
        novel_id=novel.id,
        chapter_number=chapter.number,
        result=prepared_result,
    )
    preparer_type.return_value.prepare.assert_called_once_with(
        extraction_result,
        prompt_language="en",
    )


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.AssetExtractor.extract",
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
    assert person.base_traits.startswith(
        "Task: Create an upper-body, front-facing, eye-level close-up"
    )
    assert ZHANG_SAN_TRAITS in person.base_traits


# =====================================================================
# 增量合并
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.AssetExtractor.extract",
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
    "services.extraction.extractor.AssetExtractor.extract",
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
@patch(
    "services.extraction.extractor.AssetExtractor.extract",
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
    "services.extraction.extractor.AssetExtractor.extract",
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
    "services.extraction.extractor.AssetExtractor.extract",
    side_effect=Exception("secret-handler-integration-marker"),
)
async def test_提取异常_以脱敏网关异常抛出到上层(mock_extract):
    """LLM 调用失败时向 executor 抛出稳定且脱敏的异常。"""
    novel, chapter = await _setup_env()
    handler = ExtractionTaskHandler()

    with pytest.raises(AssetExtractionGatewayError) as captured:
        await handler.execute({
            "chapter_id": chapter.id,
            "novel_id": novel.id,
            "base_url": "https://mock.com",
            "api_key": "sk-mock",
            "model": "mock-model",
            "concurrency": 1,
        })

    assert str(captured.value) == (
        "资产提取模型调用失败"
        "（错误代码：asset_extraction_gateway_error）"
    )
    assert "secret-handler-integration-marker" not in repr(captured.value)


# =====================================================================
# 并发控制
# =====================================================================

@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.AssetExtractor.extract",
    new=_mock_extract,
)
async def test_统一提取器一次返回三类资产():
    """人物、场景、道具必须由一次统一提取调用返回。"""
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

    assert len(result["persons"]) == 2
    assert len(result["scenes"]) == 1
    assert len(result["items"]) == 1


@pytest.mark.asyncio
@patch(
    "services.extraction.extractor.AssetExtractor.extract",
    new=_mock_extract,
)
async def test_旧任务并发参数不改变统一提取结果():
    """旧任务保留 concurrency 参数时仍走一次统一资产提取。"""
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
    "services.extraction.extractor.AssetExtractor.extract",
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


@pytest.mark.asyncio
async def test_handler_surfaces_token_usage_from_extractor():
    case = _orchestration_case()
    case.extractor.last_usage = {"prompt_tokens": 120, "completion_tokens": 40}

    with patch("services.extraction.handler.AsyncOpenAI", return_value=SimpleNamespace()):
        summary = await case.handler.execute(case.request_params)

    assert summary["token_usage"] == {"prompt_tokens": 120, "completion_tokens": 40}
    assert summary["persons"] == case.summary["persons"]
