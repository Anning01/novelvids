# Asset Extraction Context Layering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep one structured asset-extraction model call while separating system rules, novel metadata, the complete known-asset registry, and current chapter input into four messages managed by small, testable objects.

**Architecture:** `ExtractionTaskHandler` becomes a thin orchestrator over `ExtractionContextLoader`, `ExtractionMessageBuilder`, `ContextBudgetPolicy`, `AssetExtractor`, and `AssetUpsertService`. The model configuration supplies an optional provider-neutral character limit, the LLM schema layer remains the only output-format authority, and all asset writes occur in one transaction.

**Tech Stack:** Python 3.12, FastAPI, Tortoise ORM, Pydantic, OpenAI-compatible chat completions, pytest; Vue 3.5, TypeScript 6, Vite 8, Vitest.

## Global Constraints

- Continue to make exactly one model call per chapter extraction task.
- The four business-message roles must be exactly `system, user, user, user`.
- Include every recognized person, scene, and item in the project asset registry; do not filter it to the current chapter.
- Never silently remove assets or truncate the current chapter to fit a context limit.
- Do not put JSON examples or output-format instructions in the business prompt; Pydantic Schema remains the output contract.
- Do not introduce provider/model-name conditionals or provider-specific fallbacks.
- Preserve the public extraction API, task status, and `persons/scenes/items` response summary.
- Preserve unrelated dirty-worktree changes; stage only files owned by each task.
- Do not modify dependency versions, `uv.lock`, `package-lock.json`, CI, or secret files.
- New behavior must be developed red-green with targeted tests before full regression verification.

---

## File Structure

### New files

- `services/extraction/context.py` — immutable extraction data objects and database-backed `ExtractionContextLoader`.
- `services/extraction/messages.py` — pure `ExtractionMessageBuilder`, compact serialization, and source-chapter range compression.
- `services/extraction/budget.py` — `ContextBudgetPolicy`, report value object, and explicit over-limit exception.
- `services/extraction/persistence.py` — transactional `AssetUpsertService` and identity matching.
- `test/test_services/test_extraction_context.py` — context-loader and immutable snapshot tests.
- `test/test_services/test_extraction_messages.py` — four-message, serialization, compression, and budget tests.
- `test/test_services/test_extraction_persistence.py` — merge behavior and rollback tests.

### Existing files to modify

- `AGENTS.md` — record modular OOD/SOLID engineering rules.
- `models/config.py`, `schemas/config.py`, `services/schema_compat.py` — optional `max_context_characters` model capability.
- `controllers/chapter.py` — snapshot the configured context limit into extraction task parameters.
- `prompts/extraction.py` — retain only system-level extraction rules; remove novel/asset/chapter interpolation.
- `services/extraction/extractor.py` — accept prepared messages and remain only the model/Schema gateway.
- `services/extraction/handler.py` — thin orchestration through composed objects.
- `services/extraction/__init__.py` — expose the stable public extraction service types.
- `web/src/types.ts`, `web/src/pages/ConfigPage.vue` — allow administrators to configure the optional character limit.
- Existing extraction, config, Schema compatibility, API, and prompt tests — update contracts and retain regressions.

---

### Task 1: Record the modular OOD engineering rule

**Files:**
- Modify: `AGENTS.md:代码风格与架构`

**Interfaces:**
- Consumes: the approved design terminology.
- Produces: repository-wide instructions for modular OOD, SOLID, single responsibility, separation of concerns, and composition over inheritance.

- [ ] **Step 1: Add the approved architecture rules**

Add these exact requirements under `## 4. 代码风格与架构`:

```markdown
- 复杂功能优先采用模块化面向对象设计（OOD），遵循 SOLID、单一职责、关注点分离和组合优于继承。
- 将加载、校验、转换、外部调用、持久化和流程编排拆成接口清晰、可独立测试的协作对象；编排对象不得同时承载这些实现细节。
- 创建类必须对应独立职责、复用边界、替换策略或独立测试价值，禁止为了形式机械拆类。
- 新需求先检查并扩展现有通用对象和服务，避免复制逻辑、供应商特例和一次性分支。
- 对复杂流程保留清晰的数据对象与调用链，使错误能够定位到具体步骤和责任对象。
```

- [ ] **Step 2: Verify the rules are present and the file is clean**

Run:

```bash
rg -n "模块化面向对象设计|编排对象不得|禁止为了形式机械拆类|组合优于继承" AGENTS.md
git diff --check -- AGENTS.md
```

Expected: all four concepts are found; `git diff --check` exits 0.

- [ ] **Step 3: Commit only the project instructions**

```bash
git add AGENTS.md
git commit -m "docs(architecture): require modular object design"
```

---

### Task 2: Add the provider-neutral context character limit

**Files:**
- Modify: `models/config.py`
- Modify: `schemas/config.py`
- Modify: `services/schema_compat.py`
- Modify: `controllers/chapter.py`
- Modify: `web/src/types.ts`
- Modify: `web/src/pages/ConfigPage.vue`
- Modify: `test/test_api/test_config_api.py`
- Modify: `test/test_services/test_schema_compat.py`
- Modify: `test/test_controllers/test_chapter_controller.py`
- Modify: `web/src/api.test.ts`

**Interfaces:**
- Consumes: existing `AiModelConfig` CRUD and SQLite compatibility startup.
- Produces: `AiModelConfig.max_context_characters: int | None`, exposed by API/UI and copied into extraction task request parameters.

- [ ] **Step 1: Write failing backend configuration tests**

Extend `test_api_create_config` and add validation coverage:

```python
payload["max_context_characters"] = 120000
response = await client.post("/api/config", json=payload)
assert response.json()["data"]["max_context_characters"] == 120000

invalid = await client.post(
    "/api/config",
    json={**payload, "name": "invalid-context", "max_context_characters": 0},
)
assert invalid.json()["code"] == 422
```

Extend the Schema compatibility test so two repeated startups produce one statement containing:

```python
assert "ADD COLUMN max_context_characters INT" in script
```

Add a chapter-controller assertion:

```python
assert task.request_params["max_context_characters"] == 120000
```

- [ ] **Step 2: Run the tests and verify they fail for the missing field**

Run:

```bash
uv run pytest \
  test/test_api/test_config_api.py::test_api_create_config \
  test/test_services/test_schema_compat.py::test_ai_model_config_schema_adds_protocol_once_across_repeated_startups \
  test/test_controllers/test_chapter_controller.py::test_extract_snapshots_context_limit -q
```

Expected: FAIL because the model, schema, compatibility function, and task snapshot do not yet expose `max_context_characters`.

- [ ] **Step 3: Implement the backend field and compatibility rule**

Add to `AiModelConfig`:

```python
max_context_characters = fields.IntField(
    null=True,
    description="四层业务消息允许的最大总字符数；留空表示不预检",
)
```

Add to `AiModelConfigProperties` and `AiModelConfigOut`:

```python
max_context_characters: Optional[int] = Field(
    None,
    description="四层业务消息允许的最大总字符数",
    ge=1,
)
```

In `ensure_ai_model_config_schema`, derive one `existing` set from the current `PRAGMA` result and append this statement only when missing:

```sql
ALTER TABLE ai_model_configs ADD COLUMN max_context_characters INT;
```

In `ChapterController.extract`, snapshot:

```python
"max_context_characters": config.max_context_characters,
```

- [ ] **Step 4: Update the frontend type, form, and request payload**

Extend `AiModelConfig`:

```ts
max_context_characters?: number | null
```

Extend the form shape, `openCreate`, and `openEdit` with an empty-string UI value:

```ts
max_context_characters: '' as number | ''
```

Normalize the payload before submit:

```ts
const payload = {
  ...form.value,
  task_type: taskTypes[0],
  task_types: taskTypes,
  max_context_characters: form.value.max_context_characters || null,
}
```

Add an LLM-only field:

```vue
<label v-if="selectedCategory.id === 'llm'">
  <span>上下文字符上限</span>
  <input
    v-model.number="form.max_context_characters"
    name="model-max-context-characters"
    type="number"
    min="1"
    placeholder="留空表示不预检"
  />
</label>
```

Extend `web/src/api.test.ts` to assert the create/update request body preserves `max_context_characters: 120000`.

- [ ] **Step 5: Run backend and frontend verification**

Run:

```bash
uv run pytest test/test_api/test_config_api.py test/test_services/test_schema_compat.py test/test_controllers/test_chapter_controller.py -q
cd web && npm run test -- src/api.test.ts && npm run typecheck
```

Expected: all selected tests pass and TypeScript reports no errors.

- [ ] **Step 6: Commit the configuration capability**

```bash
git add models/config.py schemas/config.py services/schema_compat.py controllers/chapter.py \
  web/src/types.ts web/src/pages/ConfigPage.vue web/src/api.test.ts \
  test/test_api/test_config_api.py test/test_services/test_schema_compat.py \
  test/test_controllers/test_chapter_controller.py
git commit -m "feat(config): add extraction context limit"
```

---

### Task 3: Introduce immutable extraction context objects and loader

**Files:**
- Create: `services/extraction/context.py`
- Create: `test/test_services/test_extraction_context.py`

**Interfaces:**
- Consumes: `Novel`, `Chapter`, `Asset`, `AssetTypeEnum`.
- Produces:
  - `NovelExtractionMetadata`
  - `KnownAssetSnapshot`
  - `ChapterExtractionInput`
  - `ExtractionContext`
  - `ExtractionContextLoader.load(*, novel_id: int, chapter_id: int) -> ExtractionContext`

- [ ] **Step 1: Write failing loader tests**

Create fixtures with two chapters and three assets, including an asset whose `source_chapters` excludes the current chapter. Assert all three assets are loaded and unrelated fields are absent:

```python
context = await ExtractionContextLoader().load(
    novel_id=novel.id,
    chapter_id=chapter.id,
)

assert context.novel.name == "厄运之手"
assert context.novel.tags == ("都市异能", "复仇")
assert context.novel.story_outline == "宫平获得能力并反抗压迫。"
assert context.chapter.number == 1
assert context.chapter.content == chapter.content
assert {asset.canonical_name for asset in context.assets} == {
    "宫平", "蓝都保健中心", "黑色自行车"
}
assert context.assets[0].metadata.keys() <= {"role", "reference_layout"}
assert not hasattr(context.assets[0], "main_image")
```

Add ownership validation:

```python
with pytest.raises(ValueError, match="不属于小说"):
    await ExtractionContextLoader().load(
        novel_id=other_novel.id,
        chapter_id=chapter.id,
    )
```

- [ ] **Step 2: Run the loader tests to verify missing types fail**

Run:

```bash
uv run pytest test/test_services/test_extraction_context.py -q
```

Expected: collection fails because `services.extraction.context` does not exist.

- [ ] **Step 3: Implement immutable snapshots**

Import `dataclass`, `MappingProxyType`, and `Mapping`, then create frozen dataclasses:

```python
@dataclass(frozen=True)
class NovelExtractionMetadata:
    name: str
    author: str | None
    description: str | None
    tags: tuple[str, ...]
    story_outline: str | None
    project_type: str | None
    project_setting: str | None

@dataclass(frozen=True)
class KnownAssetSnapshot:
    id: int
    asset_type: int
    asset_type_name: str
    canonical_name: str
    aliases: tuple[str, ...]
    description: str | None
    base_traits: str | None
    source_chapters: tuple[int, ...]
    metadata: Mapping[str, str]

@dataclass(frozen=True)
class ChapterExtractionInput:
    id: int
    number: int
    name: str
    content: str

@dataclass(frozen=True)
class ExtractionContext:
    novel: NovelExtractionMetadata
    assets: tuple[KnownAssetSnapshot, ...]
    chapter: ChapterExtractionInput
```

Copy metadata into an immutable mapping and whitelist only `role` and `reference_layout`.

- [ ] **Step 4: Implement `ExtractionContextLoader`**

Use one chapter query, one novel query, and one ordered project-wide asset query:

```python
class ExtractionContextLoader:
    async def load(self, *, novel_id: int, chapter_id: int) -> ExtractionContext:
        chapter = await Chapter.get(id=chapter_id)
        if chapter.novel_id != novel_id:
            raise ValueError(f"章节 {chapter_id} 不属于小说 {novel_id}")
        novel = await Novel.get(id=novel_id)
        assets = await Asset.filter(novel_id=novel_id).order_by("asset_type", "id")
        return ExtractionContext(
            novel=NovelExtractionMetadata(
                name=novel.name,
                author=novel.author,
                description=novel.description,
                tags=tuple(novel.tags or ()),
                story_outline=novel.story_outline,
                project_type=novel.project_type,
                project_setting=novel.project_setting,
            ),
            assets=tuple(
                KnownAssetSnapshot(
                    id=asset.id,
                    asset_type=asset.asset_type,
                    asset_type_name=AssetTypeEnum(asset.asset_type).nickname,
                    canonical_name=asset.canonical_name,
                    aliases=tuple(asset.aliases or ()),
                    description=asset.description,
                    base_traits=asset.base_traits,
                    source_chapters=tuple(
                        sorted(int(value) for value in (asset.source_chapters or ()))
                    ),
                    metadata=MappingProxyType({
                        key: str(value)
                        for key, value in (asset.metadata or {}).items()
                        if key in {"role", "reference_layout"} and value is not None
                    }),
                )
                for asset in assets
            ),
            chapter=ChapterExtractionInput(
                id=chapter.id,
                number=chapter.number,
                name=chapter.name,
                content=chapter.content or "",
            ),
        )
```

Normalize nullable JSON fields into empty tuples and integer chapter tuples; do not copy ORM objects into the returned context.

- [ ] **Step 5: Run the context tests**

Run:

```bash
uv run pytest test/test_services/test_extraction_context.py -q
```

Expected: all loader and ownership tests pass.

- [ ] **Step 6: Commit the context boundary**

```bash
git add services/extraction/context.py test/test_services/test_extraction_context.py
git commit -m "feat(extraction): add immutable context loader"
```

---

### Task 4: Build four messages and enforce the context budget

**Files:**
- Create: `services/extraction/messages.py`
- Create: `services/extraction/budget.py`
- Modify: `prompts/extraction.py`
- Create: `test/test_services/test_extraction_messages.py`
- Modify: `test/test_services/test_prompt_language.py`

**Interfaces:**
- Consumes: `ExtractionContext`, `SINGLE_CHARACTER_VISUAL_RULES`, prompt language.
- Produces:
  - `ExtractionMessageBuilder.build(context: ExtractionContext, prompt_language: str) -> list[dict[str, str]]`
  - `compress_chapter_numbers(values: tuple[int, ...]) -> str`
  - `ContextBudgetPolicy.validate(messages: list[dict[str, str]], *, asset_count: int, chapter_characters: int) -> ContextBudgetReport`
  - `ContextBudgetExceededError`

- [ ] **Step 1: Write failing four-message tests**

Build a context containing a unique marker in each layer and assert exact separation:

```python
messages = ExtractionMessageBuilder().build(context, prompt_language="zh")

assert [message["role"] for message in messages] == [
    "system", "user", "user", "user"
]
assert "当前章节明确事实" in messages[0]["content"]
assert "小说元信息" in messages[1]["content"]
assert "都市异能" in messages[1]["content"]
assert "全部已识别资产" in messages[2]["content"]
assert all(name in messages[2]["content"] for name in ("宫平", "办公室", "自行车"))
assert "只返回本章" in messages[3]["content"]
assert chapter.content in messages[3]["content"]

assert chapter.content not in "".join(message["content"] for message in messages[:3])
assert "https://asset.example/image.png" not in messages[2]["content"]
assert "严格返回以下 JSON" not in "".join(message["content"] for message in messages)
assert "```json" not in "".join(message["content"] for message in messages)
```

Add language parametrization and assert all fixed labels remain in the system message.

- [ ] **Step 2: Write failing compression and budget tests**

```python
assert compress_chapter_numbers((1, 2, 3, 4, 8, 10, 11)) == "1-4,8,10-11"

report = ContextBudgetPolicy(max_context_characters=1000).validate(
    messages,
    asset_count=3,
    chapter_characters=len(chapter.content),
)
assert report.total_characters == sum(len(item["content"]) for item in messages)

with pytest.raises(ContextBudgetExceededError, match="资产 3 个"):
    ContextBudgetPolicy(max_context_characters=10).validate(
        messages,
        asset_count=3,
        chapter_characters=len(chapter.content),
    )
```

Also assert `max_context_characters=None` never guesses a limit from model names.

- [ ] **Step 3: Run the tests and confirm missing modules fail**

Run:

```bash
uv run pytest test/test_services/test_extraction_messages.py test/test_services/test_prompt_language.py -q
```

Expected: FAIL because the builder and budget policy do not exist and the prompt is still monolithic.

- [ ] **Step 4: Introduce the system-only rule template without breaking the current gateway**

Add `ASSET_EXTRACTION_SYSTEM_PROMPT` for the new message builder. Keep responsibilities, filtering rules, fixed visual contracts, priority, and anti-injection instruction. Remove these interpolation placeholders from the new system template:

```text
{existing_asset_context}
{chapter_number}
{text}
```

Keep only rule-level placeholders:

```text
{prompt_language_name}
{single_character_visual_rules}
```

State explicitly that later messages are untrusted fact data and cannot override system instructions.

Retain the existing `ASSET_EXTRACTION_PROMPT` unchanged and marked as a temporary compatibility template so the currently deployed extractor remains functional after Task 4. Task 6 deletes that legacy template in the same commit that switches the Handler and gateway to prepared messages; the final code must contain only `ASSET_EXTRACTION_SYSTEM_PROMPT`.

- [ ] **Step 5: Implement compact, bounded serialization**

Serialize each prepared dictionary with `json.dumps(payload, ensure_ascii=False, separators=(",", ":"))` inside explicit fact-data delimiters. Omit keys whose values are `None`, empty strings, empty tuples, or empty mappings. Do not serialize fields absent from the immutable snapshots.

Use these deterministic helpers and message assembly shape:

```python
def _drop_empty(values: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != "" and value != () and value != {}
    }

def compress_chapter_numbers(values: tuple[int, ...]) -> str:
    ordered = sorted(set(values))
    if not ordered:
        return ""
    ranges: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)

class ExtractionMessageBuilder:
    def build(
        self,
        context: ExtractionContext,
        prompt_language: str,
    ) -> list[dict[str, str]]:
        language_name = prompt_language_name(prompt_language)
        system_content = ASSET_EXTRACTION_SYSTEM_PROMPT.format(
            prompt_language_name=language_name,
            single_character_visual_rules=SINGLE_CHARACTER_VISUAL_RULES.format(
                prompt_language_name=language_name,
            ),
        )
        novel_payload = _drop_empty(asdict(context.novel))
        asset_payload = [
            _drop_empty({
                "id": asset.id,
                "asset_type": asset.asset_type,
                "asset_type_name": asset.asset_type_name,
                "canonical_name": asset.canonical_name,
                "aliases": asset.aliases,
                "description": asset.description,
                "base_traits": asset.base_traits,
                "source_chapters": compress_chapter_numbers(asset.source_chapters),
                "metadata": dict(asset.metadata),
            })
            for asset in context.assets
        ]
        chapter_payload = asdict(context.chapter)
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": _fact_block("novel_metadata", novel_payload)},
            {"role": "user", "content": _asset_registry_block(asset_payload)},
            {"role": "user", "content": _chapter_task_block(chapter_payload)},
        ]
```

Implement `_fact_block`, `_asset_registry_block`, and `_chapter_task_block` in the same file. Each function must add the approved Chinese boundary heading and serialize exactly one supplied payload; none may read the database or mutate its argument.

The asset message must include every `KnownAssetSnapshot` and this instruction before the data:

```text
该注册表仅用于身份匹配和稳定视觉一致性。只有在当前章节满足提取条件的资产才能进入响应；命中标准名称或别名时沿用标准名称。
```

- [ ] **Step 6: Implement deterministic budget validation**

```python
@dataclass(frozen=True)
class ContextBudgetReport:
    message_characters: tuple[int, ...]
    total_characters: int

class ContextBudgetExceededError(ValueError):
    pass

class ContextBudgetPolicy:
    def __init__(self, max_context_characters: int | None):
        if max_context_characters is not None and max_context_characters < 1:
            raise ValueError("上下文字符上限必须大于 0")
        self.max_context_characters = max_context_characters

    def validate(
        self,
        messages: list[dict[str, str]],
        *,
        asset_count: int,
        chapter_characters: int,
    ) -> ContextBudgetReport:
        message_characters = tuple(len(message["content"]) for message in messages)
        total_characters = sum(message_characters)
        if (
            self.max_context_characters is not None
            and total_characters > self.max_context_characters
        ):
            raise ContextBudgetExceededError(
                "资产上下文超限："
                f"资产 {asset_count} 个，章节 {chapter_characters} 字符，"
                f"请求 {total_characters} 字符，"
                f"配置上限 {self.max_context_characters} 字符"
            )
        return ContextBudgetReport(
            message_characters=message_characters,
            total_characters=total_characters,
        )
```

Reject non-positive configured limits in the constructor even though API validation should already prevent them. Never mutate `messages` during validation.

- [ ] **Step 7: Run message and prompt tests**

Run:

```bash
uv run pytest test/test_services/test_extraction_messages.py test/test_services/test_prompt_language.py -q
```

Expected: all tests pass for Chinese and English, exact layer separation, full registry inclusion, compression, and budget failure.

- [ ] **Step 8: Commit the message and budget objects**

```bash
git add prompts/extraction.py services/extraction/messages.py services/extraction/budget.py \
  test/test_services/test_extraction_messages.py test/test_services/test_prompt_language.py
git commit -m "feat(extraction): layer model context messages"
```

---

### Task 5: Extract transactional asset persistence

**Files:**
- Create: `services/extraction/persistence.py`
- Create: `test/test_services/test_extraction_persistence.py`
- Modify: `services/extraction/handler.py`
- Modify: `test/test_services/test_extraction_handler.py`

**Interfaces:**
- Consumes: `AssetExtractionResult`, novel ID, chapter number.
- Produces: `AssetUpsertService.save_result(*, novel_id: int, chapter_number: int, result: AssetExtractionResult) -> dict[str, list[dict[str, str]]]`.

- [ ] **Step 1: Move existing merge expectations into service-level failing tests**

Cover:

```python
summary = await AssetUpsertService().save_result(
    novel_id=novel.id,
    chapter_number=1,
    result=result,
)

assert summary == {
    "persons": [{"name": "宫平", "action": "updated"}],
    "scenes": [{"name": "办公室", "action": "created"}],
    "items": [{"name": "黑色自行车", "action": "created"}],
}
```

Move or parameterize these existing assertions without changing their expected behavior: `test_增量提取_合并别名和章节`, `test_增量提取_同一章节重复提取不重复追加`, `test_增量提取_别名命中且空字段不覆盖旧资料`, `test_增量提取_较早章节重跑不会回滚较新资料`, `test_正式提取覆盖项目分析的临时人物描述`, and `test_增量提取_合并别名去重`.

- [ ] **Step 2: Write a failing transaction rollback test**

Prepare `result` so its person updates `original` and its scene requires `Asset.create`. Patch that create call to fail after the update has executed, then assert the transaction restores the original state:

```python
with patch(
    "services.extraction.persistence.Asset.create",
    new=AsyncMock(side_effect=RuntimeError("forced save failure")),
):
    with pytest.raises(RuntimeError, match="forced save failure"):
        await service.save_result(
            novel_id=novel.id,
            chapter_number=1,
            result=result,
        )

assert await Asset.filter(novel_id=novel.id).count() == original_count
await original.refresh_from_db()
assert original.base_traits == original_traits
assert original.source_chapters == original_source_chapters
```

- [ ] **Step 3: Run persistence tests and verify the service is missing**

Run:

```bash
uv run pytest test/test_services/test_extraction_persistence.py -q
```

Expected: collection fails because `AssetUpsertService` does not exist.

- [ ] **Step 4: Implement `AssetUpsertService` with one Tortoise transaction**

Move `_identity_key`, `_identity_keys`, `_ordered_strings`, `RESULT_ASSET_MAP`, and `_save_assets` into `persistence.py`. Wrap all result categories in:

```python
async with in_transaction() as connection:
    for asset_type, result_key in RESULT_ASSET_MAP:
        saved = await self._save_assets(
            connection=connection,
            novel_id=novel_id,
            chapter_number=chapter_number,
            asset_type=asset_type,
            items=getattr(result, result_key),
        )
        summary[result_key] = saved
```

Every query and write must use the same connection:

```python
existing_assets = await Asset.filter(
    novel_id=novel_id,
    asset_type=asset_type.value,
).using_db(connection)
await existing.save(
    using_db=connection,
    update_fields=[
        "aliases", "description", "base_traits", "metadata",
        "source_chapters", "last_updated_chapter", "updated_at",
    ],
)
await Asset.create(
    using_db=connection,
    novel_id=novel_id,
    asset_type=asset_type.value,
    canonical_name=item.name,
    aliases=item.aliases,
    description=item.description,
    base_traits=item.base_traits,
    metadata=item_metadata,
    source_chapters=[chapter_number],
    last_updated_chapter=chapter_number,
)
```

Do not change the existing identity and anti-rollback business rules while moving them.

Keep the current extraction call working in this commit by making the existing Handler delegate only its save phase:

```python
result = await extractor.extract(
    chapter.content,
    chapter.number,
    existing_asset_context=existing_asset_context,
)
return await AssetUpsertService().save_result(
    novel_id=novel_id,
    chapter_number=chapter.number,
    result=result,
)
```

The message-building and gateway call are replaced together in Task 6, so Task 5 leaves no broken intermediate application state.

- [ ] **Step 5: Run persistence and old handler merge tests**

Run:

```bash
uv run pytest \
  test/test_services/test_extraction_persistence.py \
  test/test_services/test_extraction_handler.py -q
```

Expected: all merge, upgrade, source-chapter, and rollback tests pass.

- [ ] **Step 6: Commit transactional persistence**

```bash
git add services/extraction/persistence.py services/extraction/handler.py \
  test/test_services/test_extraction_persistence.py test/test_services/test_extraction_handler.py
git commit -m "refactor(extraction): add transactional asset upsert"
```

---

### Task 6: Compose the prepared-message gateway and extraction workflow

**Files:**
- Modify: `services/extraction/extractor.py`
- Modify: `services/extraction/handler.py`
- Modify: `services/extraction/__init__.py`
- Modify: `test/test_services/test_extraction_handler.py`
- Modify: `test/test_api/test_extraction_api.py`
- Modify: `test/test_services/test_prompt_language.py`

**Interfaces:**
- Consumes: all objects produced by Tasks 2–5 and four prepared `list[dict[str, str]]` messages.
- Produces: `AssetExtractor.extract(messages: list[dict[str, str]]) -> AssetExtractionResult`.
- Produces: the unchanged extraction task API with four-message context, one model call, context diagnostics, and atomic persistence.

- [ ] **Step 1: Write a failing gateway-boundary test**

Mock `create_json_completion` and pass four distinct messages:

```python
messages = [
    {"role": "system", "content": "rules-marker"},
    {"role": "user", "content": "novel-marker"},
    {"role": "user", "content": "assets-marker"},
    {"role": "user", "content": "chapter-marker"},
]

result = await AssetExtractor(
    client=SimpleNamespace(),
    model="test-model",
    supports_json_output=True,
).extract(messages)

assert isinstance(result, AssetExtractionResult)
assert mocked_completion.await_args.kwargs["messages"] == messages
assert mocked_completion.await_args.kwargs["response_model"] is AssetExtractionResult
assert mocked_completion.await_args.kwargs["supports_json_output"] is True
```

- [ ] **Step 2: Write a failing orchestration test with injected collaborators**

Construct mocks for loader, builder, budget-policy factory, extractor factory, and upsert service. Configure each factory to return its mock object, execute the handler, and assert the exact inputs:

```python
context_loader.load.assert_awaited_once_with(
    novel_id=novel.id,
    chapter_id=chapter.id,
)
message_builder.build.assert_called_once_with(context, prompt_language="zh")
budget_policy.validate.assert_called_once_with(
    messages,
    asset_count=len(context.assets),
    chapter_characters=len(context.chapter.content),
)
extractor.extract.assert_awaited_once_with(messages)
upsert_service.save_result.assert_awaited_once_with(
    novel_id=novel.id,
    chapter_number=context.chapter.number,
    result=extraction_result,
)
```

Assert the returned summary is exactly the upsert-service result.

- [ ] **Step 3: Write failure-path tests**

Use explicit collaborator failures and negative assertions:

```python
budget_policy.validate.side_effect = ContextBudgetExceededError("资产上下文超限")
with pytest.raises(ContextBudgetExceededError, match="资产上下文超限"):
    await handler.execute(request_params)
extractor.extract.assert_not_awaited()
upsert_service.save_result.assert_not_awaited()

budget_policy.validate.side_effect = None
extractor.extract.side_effect = ValueError("Schema validation failed")
with pytest.raises(ValueError, match="Schema validation failed"):
    await handler.execute(request_params)
upsert_service.save_result.assert_not_awaited()

context_loader.load.side_effect = ValueError("章节不属于小说")
with pytest.raises(ValueError, match="不属于小说"):
    await handler.execute(request_params)
message_builder.build.assert_not_called()
extractor.extract.assert_not_awaited()
upsert_service.save_result.assert_not_awaited()
```

For the empty-registry case, set `context.assets = ()`, return four marker messages from the builder, execute successfully, and assert `extractor.extract.assert_awaited_once_with(messages)`.

- [ ] **Step 4: Run gateway and handler tests to verify the old contracts fail**

Run:

```bash
uv run pytest \
  test/test_services/test_prompt_language.py::test_asset_extractor_forwards_prepared_messages_once \
  test/test_services/test_extraction_handler.py -q
```

Expected: FAIL because `AssetExtractor.extract` still expects text plus chapter number and `ExtractionTaskHandler` does not compose the approved objects.

- [ ] **Step 5: Make `AssetExtractor` a prepared-message gateway**

Remove Prompt construction from the gateway and change its only public extraction signature to:

```python
async def extract(
    self,
    messages: list[dict[str, str]],
) -> AssetExtractionResult:
    parsed, _ = await create_json_completion(
        self.client,
        model=self.model,
        messages=messages,
        response_model=self.response_model,
        supports_json_output=self.supports_json_output,
    )
    return AssetExtractionResult.model_validate(parsed)
```

Remove `max_text_length`, `prompt_language`, Prompt imports, and formatting from the gateway. Language belongs to `ExtractionMessageBuilder`; truncation is forbidden. Update extraction test mocks to accept `messages`.

Delete the temporary `ASSET_EXTRACTION_PROMPT` compatibility template from `prompts/extraction.py` after the gateway no longer imports it. Confirm `rg -n "ASSET_EXTRACTION_PROMPT" prompts services test` returns no matches.

- [ ] **Step 6: Implement thin dependency-injected orchestration**

Use constructor injection for stable collaborators and factories for request-bound objects:

```python
class ExtractionTaskHandler(BaseTaskHandler):
    def __init__(
        self,
        *,
        context_loader: ExtractionContextLoader | None = None,
        message_builder: ExtractionMessageBuilder | None = None,
        upsert_service: AssetUpsertService | None = None,
        budget_policy_factory: Callable[
            [int | None], ContextBudgetPolicy
        ] = ContextBudgetPolicy,
        extractor_factory: Callable[..., AssetExtractor] = AssetExtractor,
    ) -> None:
        self.context_loader = context_loader or ExtractionContextLoader()
        self.message_builder = message_builder or ExtractionMessageBuilder()
        self.upsert_service = upsert_service or AssetUpsertService()
        self.budget_policy_factory = budget_policy_factory
        self.extractor_factory = extractor_factory
```

Inside `execute`:

```python
context = await self.context_loader.load(
    novel_id=request_params["novel_id"],
    chapter_id=request_params["chapter_id"],
)
messages = self.message_builder.build(
    context,
    prompt_language=request_params.get("prompt_language", "en"),
)
report = self.budget_policy_factory(
    request_params.get("max_context_characters")
).validate(
    messages,
    asset_count=len(context.assets),
    chapter_characters=len(context.chapter.content),
)
logger.info(
    "Extraction context prepared: novel_id=%s chapter_id=%s assets=%s message_chars=%s total_chars=%s",
    request_params["novel_id"],
    request_params["chapter_id"],
    len(context.assets),
    report.message_characters,
    report.total_characters,
)
extractor = self.extractor_factory(
    AsyncOpenAI(
        api_key=request_params["api_key"],
        base_url=request_params["base_url"],
    ),
    model=request_params["model"],
    supports_json_output=request_params.get("supports_json_output", False),
)
result = await extractor.extract(messages)
return await self.upsert_service.save_result(
    novel_id=request_params["novel_id"],
    chapter_number=context.chapter.number,
    result=result,
)
```

Do not log message content, API keys, novel text, or asset visual descriptions.

- [ ] **Step 7: Run targeted backend regressions**

Run:

```bash
uv run pytest \
  test/test_services/test_extraction_context.py \
  test/test_services/test_extraction_messages.py \
  test/test_services/test_extraction_persistence.py \
  test/test_services/test_extraction_handler.py \
  test/test_services/test_prompt_language.py \
  test/test_services/test_project_analysis_handler.py \
  test/test_api/test_extraction_api.py -q
```

Expected: all selected tests pass; only the documented real-model test may skip for missing `test/.test.env`.

- [ ] **Step 8: Commit the gateway, workflow composition, and regressions**

```bash
git add services/extraction/extractor.py services/extraction/handler.py services/extraction/__init__.py \
  test/test_services/test_extraction_handler.py test/test_api/test_extraction_api.py \
  test/test_services/test_prompt_language.py
git commit -m "feat(extraction): compose layered context workflow"
```

---

### Task 7: Complete full regression and real-service acceptance

**Files:**
- Verify only: all files changed by Tasks 1–6.

**Interfaces:**
- Consumes: the completed layered extraction workflow.
- Produces: fresh evidence that backend, frontend, database compatibility, single-call behavior, and real project data satisfy the design.

- [ ] **Step 1: Run full automated verification**

Run:

```bash
uv run pytest -q
cd web && npm run test && npm run typecheck && npm run build
cd .. && git diff --check
```

Expected: backend and frontend suites pass, the production build succeeds, and `git diff --check` reports no whitespace errors. The real extraction pytest may skip only when the documented `test/.test.env` configuration is absent.

- [ ] **Step 2: Perform sanitized real-service acceptance**

With the local backend running on port 9000 and the existing project configuration:

1. Submit extraction for a chapter that already has project-wide assets.
2. Poll only task ID, status, error message, and response summary; never print `request_params`.
3. Confirm the boundary log reports message-size tuple length `4` and the full project asset count without printing message contents.
4. Confirm the task performs exactly one external completion request.
5. Confirm known assets keep their standard names and stable traits.
6. Record an asset absent from the current chapter before the run and confirm its `source_chapters` is byte-for-byte unchanged afterward.
7. Confirm every person result has all required fixed labels and no field value exactly equal to `None`, `无`, `无/None`, `未知`, `未提及`, or `无法确认`.

- [ ] **Step 3: Inspect the final diff and commit graph**

Run:

```bash
git status --short
git diff --check
git log --oneline -8
```

Expected: no unstaged implementation changes owned by this plan, no whitespace errors, and separate commits exist for instructions, configuration, context loading, message construction, persistence, and orchestration. Pre-existing unrelated dirty-worktree files may remain and must not be staged or altered.

---

## Completion Checklist

- [ ] `AGENTS.md` contains the approved modular OOD/SOLID rules.
- [ ] Model configuration exposes optional `max_context_characters` with repeated-startup compatibility.
- [ ] Context loader returns immutable, project-wide snapshots without media or secret fields.
- [ ] Message builder returns exactly four business messages in the approved order.
- [ ] Every recognized project asset appears in the registry message.
- [ ] Current chapter content appears only in the final user message.
- [ ] Business Prompt has no JSON example or duplicate output-format instruction.
- [ ] Context budget never silently truncates assets or chapter text.
- [ ] `AssetExtractor` only forwards prepared messages and validates Schema output.
- [ ] `AssetUpsertService` preserves merge rules and rolls back partial failures.
- [ ] `ExtractionTaskHandler` remains a thin orchestration object.
- [ ] Boundary logs are sanitized and contain only counts and sizes.
- [ ] Targeted tests, full pytest, frontend tests, typecheck, and production build pass.
- [ ] Real-service acceptance confirms one call, full asset context, stable identities, and no cross-chapter contamination.
