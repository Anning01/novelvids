# 账单计费模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每一次 AI 模型调用建立可审计的计费流水，为每个项目（小说）提供成本汇总，并让模型配置支持按任务类型自定义的费用模块。

**Architecture:** 新增独立计费流水表 `ModelUsageRecord`，在 `AiModelConfig` 上增加 `pricing` JSON 字段。计费逻辑收敛在 `services/billing/`（定价计算 `pricing.py`、流水写入 `recorder.py`、聚合 `aggregation.py`）。`AiTaskExecutor` 的完成/失败落点与 `VideoController.query_status` 是唯一写流水入口，写库容错、绝不打断生成主流程。前端在模型配置页加费用编辑区，新增 `/billing` 成本看板页。

**Tech Stack:** FastAPI + Tortoise ORM（异步）+ Pydantic v2 + Vue 3 + TypeScript + Vite；`decimal.Decimal` 做金额；`generate_schemas(safe=True)` + `schema_compat.py` 迁移。

**Spec:** `docs/superpowers/specs/2026-08-15-billing-cost-tracking-design.md`

## Global Constraints

- 币种统一人民币「元」（`CNY`），单币种，不做汇率。
- 历史 `AiTask`/`Video` 无 pricing/usage，成本一律 0，不回填。
- 项目 = 小说（`Novel`），`novel_id` 为项目归属。
- 金额用 `decimal.Decimal` 计算，存储四舍五入到 6 位小数（`ROUND_HALF_UP`）。
- 计费写库一律 `try/except + log`，绝不因计费失败打断生成主流程。
- 失败口径：文本按实际 token（拿到 completion 就计，含下游解析失败透出的 usage）；图片/视频仅成功计费，失败记 0。
- 迁移沿用 `Tortoise.generate_schemas(safe=True)`（新表自动建）+ `services/schema_compat.py`（已有表加列），不引入迁移框架。
- 不改变现有生成主流程的行为与接口契约；计费为旁路副作用。

---

### Task 1: 计费计算模块 `services/billing/pricing.py`

**Files:**
- Create: `services/billing/__init__.py`
- Create: `services/billing/pricing.py`
- Test: `test/test_services/test_billing_pricing.py`

**Interfaces:**
- Consumes: 无（纯函数）。
- Produces:
  - `normalize_token_usage(usage: dict | None) -> dict[str, int]` — 归一化 `prompt_tokens→input_tokens`、`completion_tokens→output_tokens`。
  - `compute_text_cost(usage: dict | None, pricing: dict | None) -> Decimal`
  - `compute_image_cost(image_count: int, clarity: str | None, pricing: dict | None) -> Decimal`
  - `compute_video_cost(seconds: float, resolution: str | None, pricing: dict | None) -> Decimal`
  - 以上三个 `compute_*` 在缺定价/缺档位时返回 `Decimal("0")`。

- [ ] **Step 1: 写失败测试**

`test/test_services/test_billing_pricing.py`:

```python
from decimal import Decimal

import pytest

from services.billing.pricing import (
    compute_image_cost,
    compute_text_cost,
    compute_video_cost,
    normalize_token_usage,
)

TEXT_PRICING = {
    "type": "text",
    "currency": "CNY",
    "input_price_per_1m": 1.0,
    "output_price_per_1m": 2.0,
}
IMAGE_PRICING = {"type": "image", "currency": "CNY", "prices": {"1K": 0.10, "2K": 0.20}}
VIDEO_PRICING = {"type": "video", "currency": "CNY", "prices": {"480p": 0.50, "720p": 1.00}}


def test_normalize_token_usage_prompt_completion_keys():
    usage = {"prompt_tokens": 1500, "completion_tokens": 500, "total_tokens": 2000}
    assert normalize_token_usage(usage) == {"input_tokens": 1500, "output_tokens": 500}


def test_normalize_token_usage_new_keys_and_empty():
    assert normalize_token_usage({"input_tokens": 10, "output_tokens": 20}) == {
        "input_tokens": 10,
        "output_tokens": 20,
    }
    assert normalize_token_usage(None) == {"input_tokens": 0, "output_tokens": 0}
    assert normalize_token_usage({}) == {"input_tokens": 0, "output_tokens": 0}


def test_compute_text_cost_rounds_to_six_decimals():
    usage = {"prompt_tokens": 1500, "completion_tokens": 500}
    # 1500/1e6*1 + 500/1e6*2 = 0.0015 + 0.001 = 0.0025
    assert compute_text_cost(usage, TEXT_PRICING) == Decimal("0.002500")


def test_compute_text_cost_missing_pricing_is_zero():
    assert compute_text_cost({"prompt_tokens": 100}, None) == Decimal("0")
    assert compute_text_cost({}, {"type": "image", "prices": {}}) == Decimal("0")


def test_compute_image_cost_multiplies_count_by_tier():
    assert compute_image_cost(3, "1K", IMAGE_PRICING) == Decimal("0.300000")
    assert compute_image_cost(1, "2K", IMAGE_PRICING) == Decimal("0.200000")


def test_compute_image_cost_missing_tier_is_zero():
    assert compute_image_cost(3, "4K", IMAGE_PRICING) == Decimal("0")
    assert compute_image_cost(3, "1K", None) == Decimal("0")


def test_compute_video_cost_multiplies_seconds_by_resolution():
    assert compute_video_cost(6.0, "720p", VIDEO_PRICING) == Decimal("6.000000")
    assert compute_video_cost(10.5, "480p", VIDEO_PRICING) == Decimal("5.250000")


def test_compute_video_cost_missing_resolution_is_zero():
    assert compute_video_cost(6.0, "4k", VIDEO_PRICING) == Decimal("0")
    assert compute_video_cost(6.0, "720p", None) == Decimal("0")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_services/test_billing_pricing.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'services.billing'`）

- [ ] **Step 3: 写最小实现**

`services/billing/__init__.py`:

```python
"""账单计费模块。"""
```

`services/billing/pricing.py`:

```python
"""计费规则：token 归一化与三种维度的成本计算。"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY_QUANT = Decimal("0.000001")
_TOKEN_DIVISOR = Decimal("1_000_000")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _as_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def normalize_token_usage(usage: dict | None) -> dict[str, int]:
    """归一化 token 用量键：兼容 prompt_tokens/completion_tokens 命名。"""
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0}

    def _int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0))
    return {"input_tokens": _int(input_tokens), "output_tokens": _int(output_tokens)}


def compute_text_cost(usage: dict | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "text":
        return Decimal("0")
    tokens = normalize_token_usage(usage)
    input_price = _as_decimal(pricing.get("input_price_per_1m"))
    output_price = _as_decimal(pricing.get("output_price_per_1m"))
    cost = (
        (Decimal(tokens["input_tokens"]) / _TOKEN_DIVISOR) * input_price
        + (Decimal(tokens["output_tokens"]) / _TOKEN_DIVISOR) * output_price
    )
    return _money(cost)


def compute_image_cost(image_count: int, clarity: str | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "image":
        return Decimal("0")
    prices = pricing.get("prices") or {}
    if not isinstance(prices, dict) or clarity not in prices:
        return Decimal("0")
    return _money(_as_decimal(prices[clarity]) * Decimal(int(image_count or 0)))


def compute_video_cost(seconds: float, resolution: str | None, pricing: dict | None) -> Decimal:
    if not isinstance(pricing, dict) or pricing.get("type") != "video":
        return Decimal("0")
    prices = pricing.get("prices") or {}
    if not isinstance(prices, dict) or resolution not in prices:
        return Decimal("0")
    return _money(_as_decimal(prices[resolution]) * _as_decimal(seconds))
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_services/test_billing_pricing.py -q`
Expected: PASS（11 passed）

- [ ] **Step 5: Commit**

```bash
git add services/billing test/test_services/test_billing_pricing.py
git commit -m "feat(billing): 新增计费计算与 token 归一化纯函数"
```

---

### Task 2: 数据模型 `ModelUsageRecord` + `AiModelConfig.pricing` 字段与迁移

**Files:**
- Create: `models/usage_record.py`
- Modify: `models/config.py`（加 `pricing` 字段）
- Modify: `services/schema_compat.py`（加 `pricing` 列）
- Modify: `schemas/config.py`（`AiModelConfigProperties` 加 `pricing`）
- Modify: `test/conftest.py`（`clear_db` 清理新表）
- Modify: `test/test_services/test_schema_compat.py`（补充 `pricing` 列断言）
- Test: `test/test_models/test_usage_record.py`

**Interfaces:**
- Consumes: `models/_base.py` 的 `AbstractBaseModel`（`from models._base import AbstractBaseModel`）。
- Produces: `ModelUsageRecord` 表（`model_usage_records`）；`AiModelConfig.pricing`（JSONField，可空）。字段名供后续任务引用：`novel_id, task_type, billing_type, ai_task_id, video_id, model_config_id, model_name, model, model_type, pricing_snapshot, usage, cost, currency, status`。

- [ ] **Step 1: 写失败测试**

`test/test_models/test_usage_record.py`:

```python
import pytest

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_usage_record_creates_and_defaults():
    record = await ModelUsageRecord.create(
        novel_id=1,
        task_type=AiTaskTypeEnum.storyboard.value,
        billing_type="text",
        model="deepseek-chat",
        status=TaskStatusEnum.completed.value,
    )
    assert record.id is not None
    assert record.usage == {}
    assert record.currency == "CNY"
    assert record.cost == 0
    assert record.model_name is None
    assert record.pricing_snapshot is None


@pytest.mark.asyncio
async def test_ai_model_config_pricing_field_roundtrips():
    pricing = {"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0}
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="priced-llm",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="deepseek-chat",
        pricing=pricing,
    )
    assert config.pricing == pricing
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_models/test_usage_record.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'models.usage_record'`）

- [ ] **Step 3: 写最小实现**

`models/usage_record.py`:

```python
"""模型调用计费流水表。"""

from tortoise import fields

from models._base import AbstractBaseModel
from utils.enums import TaskStatusEnum


class ModelUsageRecord(AbstractBaseModel):
    """一行 = 一次可计费模型调用；一次任务可能落多条流水。"""

    novel_id = fields.IntField(db_index=True, description="项目归属（Novel.id）")
    task_type = fields.IntField(db_index=True, description="AI 任务类型")
    billing_type = fields.CharField(max_length=16, description="计费维度：text/image/video")
    ai_task_id = fields.UUIDField(null=True, description="关联 AiTask")
    video_id = fields.IntField(null=True, description="关联 Video")
    model_config_id = fields.IntField(null=True, description="模型配置 ID 快照")
    model_name = fields.CharField(max_length=100, null=True, description="配置名快照")
    model = fields.CharField(max_length=200, description="供应商模型 ID 快照")
    model_type = fields.CharField(max_length=40, null=True, description="图片/视频能力类型快照")
    pricing_snapshot = fields.JSONField(null=True, description="调用时刻定价快照")
    usage = fields.JSONField(default=dict, description="用量（token/张数/秒数）")
    cost = fields.DecimalField(max_digits=18, decimal_places=6, default=0, description="成本（元）")
    currency = fields.CharField(max_length=8, default="CNY", description="币种")
    status = fields.IntField(default=TaskStatusEnum.completed.value, description="任务状态")

    class Meta:
        table = "model_usage_records"
        table_description = "AI 模型调用计费流水表"
```

`models/config.py` —— 在 `max_context_characters` 字段后加：

```python
    pricing = fields.JSONField(
        null=True,
        description="计费费用模块，按任务类型分 text/image/video 三种结构",
    )
```

`services/schema_compat.py` —— 在 `ensure_ai_model_config_schema` 的 `existing` 判断块后追加（与其它 `ALTER TABLE` 并列）：

```python
    if "pricing" not in existing:
        statements.append(
            "ALTER TABLE ai_model_configs ADD COLUMN pricing JSON;"
        )
```

`schemas/config.py` —— 在 `AiModelConfigProperties` 的 `max_context_characters` 字段后加：

```python
    pricing: Optional[dict] = Field(
        None,
        description="计费费用模块：文本={input_price_per_1m,output_price_per_1m}，图片/视频={prices}",
    )
```

`test/conftest.py` —— 在 `clear_db` 里补清理（导入列表与删除顺序）：

```python
    from models.usage_record import ModelUsageRecord
    ...
    await ModelUsageRecord.all().delete()
```

（把 `from models.usage_record import ModelUsageRecord` 加到 `clear_db` 顶部那串 `from models...` 导入中，并在 `await GeneralConfig.all().delete()` 之前加 `await ModelUsageRecord.all().delete()`。）

`test/test_services/test_schema_compat.py` —— 两处 `completed` 列清单补 `{"name": "pricing"}`，并在脚本断言里加：

```python
    assert "ADD COLUMN pricing JSON" in script
```

- [ ] **Step 4: 运行确认通过**

Run:
```bash
uv run pytest test/test_models/test_usage_record.py test/test_services/test_schema_compat.py -q
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add models/usage_record.py models/config.py services/schema_compat.py schemas/config.py test/conftest.py test/test_models/test_usage_record.py test/test_services/test_schema_compat.py
git commit -m "feat(billing): 新增计费流水表与模型 pricing 字段及迁移"
```

---

### Task 3: 模型定价校验 `controllers/config.py`

**Files:**
- Modify: `controllers/config.py`（`_validate_pricing` + 调用点）
- Test: `test/test_controllers/test_config_pricing_validation.py`

**Interfaces:**
- Consumes: `services/image_generation/capabilities.py::capabilities_for`（`image_capabilities_for`）、`services/video/capabilities.py::capabilities_for`（`video_capabilities_for`）。
- Produces: `AiModelConfigController._validate_pricing(data, instance=None)`，对 create/update/patch 生效；非法 pricing 抛 `HTTPException(400)`。

- [ ] **Step 1: 写失败测试**

`test/test_controllers/test_config_pricing_validation.py`:

```python
import pytest
from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from schemas.config import AiModelConfigCreate
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_文本模型接受合法pricing():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="text-priced",
        base_url="https://api.example.com",
        api_key="sk",
        model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    ))
    assert config.pricing["type"] == "text"


@pytest.mark.asyncio
async def test_文本模型缺少价格字段被拒绝():
    with pytest.raises(HTTPException, match="input_price_per_1m"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.extraction.value,
            name="bad-text",
            base_url="https://api.example.com",
            api_key="sk",
            model="m",
            pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0},
        ))


@pytest.mark.asyncio
async def test_生图模型接受合法档位pricing():
    config = await ai_model_config_controller.create(AiModelConfigCreate(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image-priced",
        base_url="https://ark.example.com/api/v3",
        api_key="sk",
        model="m",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.10, "2K": 0.20}},
    ))
    assert config.pricing["prices"]["1K"] == 0.10


@pytest.mark.asyncio
async def test_生图模型非法档位被拒绝():
    with pytest.raises(HTTPException, match="不支持的清晰度档位"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.reference_image.value,
            name="bad-image",
            base_url="https://ark.example.com/api/v3",
            api_key="sk",
            model="m",
            api_protocol="volcengine_ark",
            image_model_type="seedream_5_pro",
            pricing={"type": "image", "currency": "CNY", "prices": {"9K": 0.10}},
        ))


@pytest.mark.asyncio
async def test_视频模型非法分辨率被拒绝():
    with pytest.raises(HTTPException, match="不支持的清晰度档位|分辨率档位"):
        await ai_model_config_controller.create(AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="bad-video",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key="sk",
            model="m",
            api_protocol="volcengine_ark",
            video_model_type="seedance_2",
            pricing={"type": "video", "currency": "CNY", "prices": {"8k": 1.0}},
        ))
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_controllers/test_config_pricing_validation.py -q`
Expected: FAIL（非法档位未触发校验，断言不通过）

- [ ] **Step 3: 写最小实现**

在 `controllers/config.py` 顶部加三个模块级校验函数（放在 `AiModelConfigController` 类定义之前），并在类的 `_validate_generation_payload` 里追加 `cls._validate_pricing(data, instance)`：

```python
def _validate_text_pricing(pricing: dict) -> None:
    if pricing.get("type") != "text":
        raise HTTPException(status_code=400, detail="文本模型的费用配置 type 必须为 text")
    for key in ("input_price_per_1m", "output_price_per_1m"):
        value = pricing.get(key)
        if value is None or not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=f"文本费用缺少合法的 {key}")


def _validate_image_pricing(pricing: dict, model_type) -> None:
    if pricing.get("type") != "image":
        raise HTTPException(status_code=400, detail="生图模型的费用配置 type 必须为 image")
    prices = pricing.get("prices")
    if not isinstance(prices, dict):
        raise HTTPException(status_code=400, detail="生图费用需要 prices 档位对象")
    allowed = set(image_capabilities_for(model_type).clarities)
    for tier, value in prices.items():
        if tier not in allowed:
            raise HTTPException(status_code=400, detail=f"生图费用包含不支持的清晰度档位：{tier}")
        if not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=f"清晰度档位 {tier} 的费用必须为非负数字")


def _validate_video_pricing(pricing: dict, model_type) -> None:
    if pricing.get("type") != "video":
        raise HTTPException(status_code=400, detail="视频模型的费用配置 type 必须为 video")
    prices = pricing.get("prices")
    if not isinstance(prices, dict):
        raise HTTPException(status_code=400, detail="视频费用需要 prices 档位对象")
    allowed = set(video_capabilities_for(model_type).resolutions)
    for tier, value in prices.items():
        if tier not in allowed:
            raise HTTPException(status_code=400, detail=f"视频费用包含不支持的分辨率档位：{tier}")
        if not isinstance(value, (int, float)) or value < 0:
            raise HTTPException(status_code=400, detail=f"分辨率档位 {tier} 的费用必须为非负数字")
```

在 `AiModelConfigController` 内加：

```python
    @staticmethod
    def _validate_pricing(data: dict, instance: AiModelConfig | None = None) -> None:
        pricing = data.get("pricing")
        if pricing is None:
            return
        if not isinstance(pricing, dict):
            raise HTTPException(status_code=400, detail="费用配置必须是对象")
        task_types = data.get("task_types")
        if task_types is None and instance is not None:
            task_types = instance.task_types or [instance.task_type]
        task_types = [int(value) for value in (task_types or [])]
        if AiTaskTypeEnum.reference_image.value in task_types:
            model_type = data.get("image_model_type") or (
                instance.image_model_type if instance else None
            )
            _validate_image_pricing(pricing, model_type)
            return
        if AiTaskTypeEnum.video.value in task_types:
            model_type = data.get("video_model_type") or (
                instance.video_model_type if instance else None
            )
            _validate_video_pricing(pricing, model_type)
            return
        _validate_text_pricing(pricing)
```

把 `_validate_generation_payload` 改为：

```python
    @classmethod
    def _validate_generation_payload(cls, data: dict, instance: AiModelConfig | None = None) -> None:
        cls._validate_image_payload(data, instance)
        cls._validate_video_payload(data, instance)
        cls._validate_pricing(data, instance)
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_controllers/test_config_pricing_validation.py test/test_controllers/test_config_controller.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add controllers/config.py test/test_controllers/test_config_pricing_validation.py
git commit -m "feat(billing): 模型配置定价结构与档位校验"
```

---

### Task 4: 计费写入器 `services/billing/recorder.py`

**Files:**
- Create: `services/billing/recorder.py`
- Test: `test/test_services/test_billing_recorder.py`

**Interfaces:**
- Consumes: `ModelUsageRecord`（Task 2）、`services.billing.pricing`（Task 1）。
- Produces: 单例 `billing_recorder`，方法：
  - `record_text(*, novel_id, task_type, model_config_id=None, fallback_model=None, token_usage=None, status=TaskStatusEnum.completed.value, ai_task_id=None)`
  - `record_image(*, novel_id, task_type, model_config_id=None, fallback_model=None, image_count=0, clarity=None, status=..., ai_task_id=None)`
  - `record_video(*, novel_id, model_config_id=None, fallback_model=None, seconds=0.0, resolution=None, status=..., video_id=None)`
  - 均返回 `ModelUsageRecord | None`（写失败返回 None）。

- [ ] **Step 1: 写失败测试**

`test/test_services/test_billing_recorder.py`:

```python
from decimal import Decimal

import pytest

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.billing.recorder import billing_recorder
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_record_text_snapshots_pricing_and_cost():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm",
        base_url="https://api.example.com",
        api_key="sk",
        model="deepseek-chat",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    record = await billing_recorder.record_text(
        novel_id=7,
        task_type=AiTaskTypeEnum.extraction.value,
        model_config_id=config.id,
        token_usage={"prompt_tokens": 1500, "completion_tokens": 500},
        status=TaskStatusEnum.completed.value,
    )
    assert record is not None
    assert record.billing_type == "text"
    assert record.model_config_id == config.id
    assert record.model_name == "llm"
    assert record.model == "deepseek-chat"
    assert record.pricing_snapshot == config.pricing
    assert record.cost == Decimal("0.002500")


@pytest.mark.asyncio
async def test_record_image_only_bills_on_provided_count():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image",
        base_url="https://ark.example.com/api/v3",
        api_key="sk",
        model="img",
        api_protocol="volcengine_ark",
        image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.10}},
    )
    record = await billing_recorder.record_image(
        novel_id=7,
        task_type=AiTaskTypeEnum.reference_image.value,
        model_config_id=config.id,
        image_count=3,
        clarity="1K",
        status=TaskStatusEnum.completed.value,
    )
    assert record.billing_type == "image"
    assert record.cost == Decimal("0.300000")
    assert record.model_type == "seedream_5_pro"


@pytest.mark.asyncio
async def test_record_video_uses_video_task_type_and_cost():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key="sk",
        model="vid",
        api_protocol="volcengine_ark",
        video_model_type="seedance_2",
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 1.0}},
    )
    record = await billing_recorder.record_video(
        novel_id=7,
        model_config_id=config.id,
        seconds=6.0,
        resolution="720p",
        status=TaskStatusEnum.completed.value,
        video_id=11,
    )
    assert record.billing_type == "video"
    assert record.task_type == AiTaskTypeEnum.video.value
    assert record.video_id == 11
    assert record.cost == Decimal("6.000000")


@pytest.mark.asyncio
async def test_record_missing_config_writes_zero_cost_snapshot_none():
    record = await billing_recorder.record_text(
        novel_id=7,
        task_type=AiTaskTypeEnum.extraction.value,
        model_config_id=999999,
        fallback_model="ghost-model",
        token_usage={"prompt_tokens": 100},
        status=TaskStatusEnum.failed.value,
    )
    assert record is not None
    assert record.pricing_snapshot is None
    assert record.model == "ghost-model"
    assert record.cost == Decimal("0")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_services/test_billing_recorder.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'services.billing.recorder'`）

- [ ] **Step 3: 写最小实现**

`services/billing/recorder.py`:

```python
"""计费流水写入器：从 model_config_id 快照定价并落 ModelUsageRecord。"""

import logging

from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.billing.pricing import (
    compute_image_cost,
    compute_text_cost,
    compute_video_cost,
    normalize_token_usage,
)
from utils.enums import AiTaskTypeEnum, TaskStatusEnum

logger = logging.getLogger(__name__)


class BillingRecorder:
    @staticmethod
    async def _config(model_config_id):
        if model_config_id is None:
            return None
        return await AiModelConfig.get_or_none(id=model_config_id)

    async def _create(
        self,
        *,
        novel_id: int,
        task_type: int,
        billing_type: str,
        config: AiModelConfig | None,
        fallback_model: str | None,
        usage: dict,
        cost,
        status: int,
        ai_task_id=None,
        video_id=None,
    ) -> ModelUsageRecord | None:
        try:
            return await ModelUsageRecord.create(
                novel_id=novel_id,
                task_type=task_type,
                billing_type=billing_type,
                ai_task_id=ai_task_id,
                video_id=video_id,
                model_config_id=config.id if config else None,
                model_name=config.name if config else None,
                model=(config.model if config else fallback_model) or "",
                model_type=(config.image_model_type or config.video_model_type) if config else None,
                pricing_snapshot=config.pricing if config else None,
                usage=usage,
                cost=cost,
                currency="CNY",
                status=status,
            )
        except Exception:
            logger.exception(
                "billing record write failed task_type=%s billing_type=%s",
                task_type,
                billing_type,
            )
            return None

    async def record_text(
        self,
        *,
        novel_id: int,
        task_type: int,
        model_config_id=None,
        fallback_model=None,
        token_usage=None,
        status: int = TaskStatusEnum.completed.value,
        ai_task_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = normalize_token_usage(token_usage)
        cost = compute_text_cost(token_usage, config.pricing if config else None)
        return await self._create(
            novel_id=novel_id,
            task_type=task_type,
            billing_type="text",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            ai_task_id=ai_task_id,
        )

    async def record_image(
        self,
        *,
        novel_id: int,
        task_type: int,
        model_config_id=None,
        fallback_model=None,
        image_count: int = 0,
        clarity: str | None = None,
        status: int = TaskStatusEnum.completed.value,
        ai_task_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = {"image_count": int(image_count or 0), "clarity": clarity}
        cost = compute_image_cost(image_count, clarity, config.pricing if config else None)
        return await self._create(
            novel_id=novel_id,
            task_type=task_type,
            billing_type="image",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            ai_task_id=ai_task_id,
        )

    async def record_video(
        self,
        *,
        novel_id: int,
        model_config_id=None,
        fallback_model=None,
        seconds: float = 0.0,
        resolution: str | None = None,
        status: int = TaskStatusEnum.completed.value,
        video_id=None,
    ) -> ModelUsageRecord | None:
        config = await self._config(model_config_id)
        usage = {"seconds": seconds, "resolution": resolution}
        cost = compute_video_cost(seconds, resolution, config.pricing if config else None)
        return await self._create(
            novel_id=novel_id,
            task_type=AiTaskTypeEnum.video.value,
            billing_type="video",
            config=config,
            fallback_model=fallback_model,
            usage=usage,
            cost=cost,
            status=status,
            video_id=video_id,
        )


billing_recorder = BillingRecorder()
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_services/test_billing_recorder.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```bash
git add services/billing/recorder.py test/test_services/test_billing_recorder.py
git commit -m "feat(billing): 计费流水写入器（定价快照 + 容错落库）"
```

---

### Task 5: usage 透出（JSON 输出 / 提取 / 项目分析）

**Files:**
- Modify: `services/llm/json_output.py`（`completion_usage` + 异常携带 usage）
- Modify: `services/extraction/extractor.py`（`last_usage` + 网关异常携带 usage）
- Modify: `services/extraction/handler.py`（结果加 `token_usage`）
- Modify: `services/project_analysis/handler.py`（捕获 completion usage + 返回计费键）
- Test: `test/test_services/test_json_output.py`（新增）、`test/test_services/test_extraction_handler.py`（新增）、`test/test_services/test_project_analysis_handler.py`（新增）

**Interfaces:**
- Consumes: `create_json_completion`（返回 `(parsed, completion)`）。
- Produces: `completion_usage(completion) -> dict`；`AssetExtractor.last_usage`；`AssetExtractionGatewayError.usage`；handler 结果新增键 `token_usage`（提取/分镜/项目分析）、`llm_config_id`/`llm_model`/`image_usage`/`image_config_id`/`image_model`（项目分析）。

- [ ] **Step 1: 写失败测试**

在 `test/test_services/test_json_output.py` 末尾追加：

```python
from services.llm.json_output import JsonCompletionError, completion_usage


def test_completion_usage_reads_openai_usage():
    completion = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=12, completion_tokens=34, total_tokens=46))
    assert completion_usage(completion) == {
        "prompt_tokens": 12,
        "completion_tokens": 34,
        "total_tokens": 46,
    }


def test_completion_usage_missing_usage_is_empty():
    assert completion_usage(SimpleNamespace()) == {}


@pytest.mark.asyncio
async def test_parse_failure_carries_usage():
    client, _ = fake_client("not json at all", finish_reason="stop")
    # 给 fake completion 挂上 usage
    original = client.chat.completions.create.return_value
    original.usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    with pytest.raises(JsonCompletionError) as captured:
        await create_json_completion(
            client,
            model="m",
            messages=[{"role": "user", "content": "x"}],
            response_model=ExamAnswer,
        )
    assert captured.value.usage["prompt_tokens"] == 10
```

在 `test/test_services/test_extraction_handler.py` 末尾追加（复用已有 `_orchestration_case` 和 mock 约定）：

```python
@pytest.mark.asyncio
async def test_handler_surfaces_token_usage_from_extractor():
    case = _orchestration_case()
    case.extractor.last_usage = {"prompt_tokens": 120, "completion_tokens": 40}

    with patch("services.extraction.handler.AsyncOpenAI", return_value=SimpleNamespace()):
        summary = await case.handler.execute(case.request_params)

    assert summary["token_usage"] == {"prompt_tokens": 120, "completion_tokens": 40}
    assert summary["persons"] == case.summary["persons"]
```

在 `test/test_services/test_project_analysis_handler.py` 末尾追加（复用 `FakeLlmClient`）：

```python
from services.project_analysis.handler import ProjectAnalysisTaskHandler


class FakeLlmClientWithUsage(FakeLlmClient):
    def __init__(self, analysis: BookAnalysis):
        super().__init__(analysis)
        self.create.return_value.usage = SimpleNamespace(
            prompt_tokens=200, completion_tokens=80, total_tokens=280
        )


@pytest.mark.asyncio
async def test_project_analysis_result_carries_billing_keys():
    novel = await Novel.create(name="计费分析", content="第1章 起\n林舟出发。")
    llm = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.project_analysis.value,
        task_types=[AiTaskTypeEnum.project_analysis.value],
        name="llm", base_url="https://llm.example.com", api_key="k", model="llm-model",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
        is_active=True,
    )
    image = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.reference_image.value,
        name="image", base_url="https://image.example.com", api_key="k", model="img-model",
        api_protocol="volcengine_ark", image_model_type="seedream_5_pro",
        pricing={"type": "image", "currency": "CNY", "prices": {"1K": 0.10}},
        is_active=True,
    )
    analysis = BookAnalysis(
        book_types=["冒险"], story_outline="林舟出发。",
        key_characters=[KeyCharacter(
            name="林舟", aliases=[], role="主角", description="青年。",
            base_traits=STRUCTURED_PERSON_TRAITS, chapter_numbers=[1],
        )],
    )
    llm_client = FakeLlmClientWithUsage(analysis)
    generated_image = SimpleNamespace(url="https://example.com/cover.png", b64_json=None)

    with (
        patch("services.project_analysis.handler.AsyncOpenAI", return_value=llm_client),
        patch("services.project_analysis.handler.generate_images", new=AsyncMock(return_value=[generated_image])),
        patch("services.project_analysis.handler._save_cover", new=AsyncMock(return_value="/media/covers/c.png")),
    ):
        result = await ProjectAnalysisTaskHandler().execute({"novel_id": novel.id})

    assert result["token_usage"]["prompt_tokens"] == 200
    assert result["llm_config_id"] == llm.id
    assert result["llm_model"] == "llm-model"
    assert result["image_usage"] == {"image_count": 1, "clarity": "1K"}
    assert result["image_config_id"] == image.id
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_services/test_json_output.py test/test_services/test_extraction_handler.py test/test_services/test_project_analysis_handler.py -q`
Expected: FAIL（`completion_usage`/`JsonCompletionError` 未定义，`last_usage` 缺失，项目分析结果缺键）

- [ ] **Step 3: 写最小实现**

`services/llm/json_output.py` —— 替换异常类定义并新增 `completion_usage`：

```python
class JsonCompletionTruncatedError(ValueError):
    """The provider stopped before returning a complete structured response."""

    def __init__(self, message: str, usage: dict | None = None) -> None:
        super().__init__(message)
        self.usage = usage or {}


class JsonCompletionError(ValueError):
    """Structured JSON completion failed; carries token usage for billing."""

    def __init__(self, message: str, usage: dict | None = None) -> None:
        super().__init__(message)
        self.usage = usage or {}


def completion_usage(completion: Any) -> dict[str, int]:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
```

把 `create_json_completion` 后半段改为：

```python
    completion = await client.chat.completions.create(**request)
    usage = completion_usage(completion)
    message = completion.choices[0].message
    finish_reason = getattr(completion.choices[0], "finish_reason", None)
    if finish_reason == "length":
        raise JsonCompletionTruncatedError(
            "模型输出达到 token 上限，结构化 JSON 未完成", usage=usage
        )
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise JsonCompletionError(f"模型拒绝生成 JSON：{refusal}", usage=usage)

    try:
        payload = _extract_json(message.content or "")
    except ValueError as exc:
        raise JsonCompletionError(str(exc), usage=usage) from None
    return response_model.model_validate(payload), completion
```

`services/extraction/extractor.py` —— 改 `AssetExtractionGatewayError` 和 `AssetExtractor`：

```python
class AssetExtractionGatewayError(RuntimeError):
    """Stable, content-free extraction boundary failure."""

    error_code = ASSET_EXTRACTION_GATEWAY_ERROR_CODE

    def __init__(self, usage: dict | None = None) -> None:
        super().__init__(ASSET_EXTRACTION_GATEWAY_ERROR_MESSAGE)
        self.usage = usage or {}
```

`AssetExtractor.__init__` 末尾加 `self.last_usage: dict = {}`；`extract` 改为：

```python
    async def extract(
        self,
        messages: list[dict[str, str]],
    ) -> AssetExtractionResult:
        try:
            parsed, completion = await create_json_completion(
                self.client,
                model=self.model,
                messages=messages,
                response_model=self.response_model,
                supports_json_output=self.supports_json_output,
            )
            self.last_usage = completion_usage(completion)
            return AssetExtractionResult.model_validate(parsed)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise AssetExtractionGatewayError(
                usage=getattr(error, "usage", None) or {}
            ) from None
```

（在 extractor.py 顶部导入 `completion_usage`：`from services.llm.json_output import create_json_completion, completion_usage`。）

`services/extraction/handler.py` —— 成功路径末尾改为：

```python
        prepared_result = self.prompt_preparer.prepare(
            result,
            prompt_language=prompt_language,
        )
        summary = await self.upsert_service.save_result(
            novel_id=novel_id,
            chapter_number=context.chapter.number,
            result=prepared_result,
        )
        return {**summary, "token_usage": getattr(extractor, "last_usage", {})}
```

`services/project_analysis/handler.py` —— 导入 `completion_usage`，捕获 completion，返回计费键：

把 `analysis, _ = await create_json_completion(...)` 改为 `analysis, completion = await create_json_completion(...)`；`token_usage = completion_usage(completion)`。

把 `return {**analysis.model_dump(), "chapter_count": len(chapters), "cover": cover}` 改为：

```python
        return {
            **analysis.model_dump(),
            "chapter_count": len(chapters),
            "cover": cover,
            "token_usage": token_usage,
            "llm_config_id": llm_config.id,
            "llm_model": llm_config.model,
            "image_usage": {"image_count": 1, "clarity": cover_selection.clarity},
            "image_config_id": image_config.id,
            "image_model": image_config.model,
        }
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_services/test_json_output.py test/test_services/test_extraction_handler.py test/test_services/test_project_analysis_handler.py -q`
Expected: PASS（含既有用例，无回归）

- [ ] **Step 5: Commit**

```bash
git add services/llm/json_output.py services/extraction/extractor.py services/extraction/handler.py services/project_analysis/handler.py test/test_services/test_json_output.py test/test_services/test_extraction_handler.py test/test_services/test_project_analysis_handler.py
git commit -m "feat(billing): 透出 token 用量并让 JSON 异常携带 usage"
```

---

### Task 6: 埋点提交点 + executor 落流水

**Files:**
- Modify: `controllers/chapter.py`（`extract` 加 `model_config_id`）
- Modify: `controllers/asset.py`（`reference` 加 `model_config_id`）
- Modify: `controllers/scene.py`（`generate` 加 `model_config_id` 与 `novel_id`）
- Modify: `services/billing/recorder.py`（新增 `record_ai_task_usage`）
- Modify: `services/ai_task_executor.py`（`_fail` 增加 `error`，完成/失败调用 `record_ai_task_usage`）
- Test: `test/test_services/test_ai_task_executor.py`（新增计费用例）

**Interfaces:**
- Consumes: `billing_recorder`（Task 4）、`record_ai_task_usage`（本任务新增）。
- Produces: `record_ai_task_usage(task, result, error)`；request_params 新增 `model_config_id`（提取/参考图/分镜）与 `novel_id`（分镜）。

- [ ] **Step 1: 写失败测试**

在 `test/test_services/test_ai_task_executor.py` 末尾追加：

```python
from models.usage_record import ModelUsageRecord


class TextBillingHandler(BaseTaskHandler):
    async def execute(self, request_params: dict) -> dict:
        return {"token_usage": {"prompt_tokens": 1000, "completion_tokens": 500}}


class FailWithUsageHandler(BaseTaskHandler):
    async def execute(self, request_params: dict) -> dict:
        error = RuntimeError("解析失败")
        error.usage = {"prompt_tokens": 200, "completion_tokens": 100}
        raise error


@pytest.mark.asyncio
async def test_run_完成落文本流水():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm", base_url="https://api.example.com", api_key="k", model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, TextBillingHandler())
    task = await executor.submit(AiTaskTypeEnum.extraction, {
        "novel_id": 5, "model_config_id": config.id, "model": "m",
    })
    await executor.run(task)

    record = await ModelUsageRecord.filter(novel_id=5).first()
    assert record is not None
    assert record.billing_type == "text"
    assert record.status == TaskStatusEnum.completed.value
    assert record.cost > 0


@pytest.mark.asyncio
async def test_run_文本失败透出usage仍计费():
    executor = AiTaskExecutor()
    executor.register(AiTaskTypeEnum.extraction, FailWithUsageHandler())
    task = await executor.submit(AiTaskTypeEnum.extraction, {"novel_id": 6})
    await executor.run(task)

    record = await ModelUsageRecord.filter(novel_id=6).first()
    assert record is not None
    assert record.status == TaskStatusEnum.failed.value
    assert record.usage["input_tokens"] == 200
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_services/test_ai_task_executor.py -q`
Expected: FAIL（`record_ai_task_usage` 未定义，流水未落库）

- [ ] **Step 3: 写最小实现**

`controllers/chapter.py` —— `extract` 的 `request_params` 加 `"model_config_id": config.id`。

`controllers/asset.py` —— `reference` 的 `request_params` 加 `"model_config_id": config.id`。

`controllers/scene.py` —— `generate` 的 `request_params` 加 `"model_config_id": config.id` 和 `"novel_id": chapter.novel_id`。

`services/billing/recorder.py` —— 追加：

```python
async def record_ai_task_usage(task, result: dict | None, error: Exception | None = None) -> None:
    """AiTaskExecutor 完成/失败后的统一计费落点。"""
    try:
        request_params = task.request_params or {}
        novel_id = request_params.get("novel_id")
        if novel_id is None:
            return
        task_type = task.task_type
        status = task.status
        if task_type == AiTaskTypeEnum.reference_image.value:
            await billing_recorder.record_image(
                novel_id=novel_id,
                task_type=task_type,
                model_config_id=request_params.get("model_config_id"),
                fallback_model=request_params.get("model"),
                image_count=len((result or {}).get("images") or []),
                clarity=request_params.get("clarity"),
                status=status,
                ai_task_id=task.id,
            )
            return
        if task_type == AiTaskTypeEnum.project_analysis.value:
            res = result or {}
            token_usage = res.get("token_usage") or getattr(error, "usage", None) or {}
            await billing_recorder.record_text(
                novel_id=novel_id,
                task_type=task_type,
                model_config_id=res.get("llm_config_id"),
                fallback_model=res.get("llm_model"),
                token_usage=token_usage,
                status=status,
                ai_task_id=task.id,
            )
            image_usage = res.get("image_usage") or {}
            if image_usage:
                await billing_recorder.record_image(
                    novel_id=novel_id,
                    task_type=task_type,
                    model_config_id=res.get("image_config_id"),
                    fallback_model=res.get("image_model"),
                    image_count=image_usage.get("image_count", 0),
                    clarity=image_usage.get("clarity"),
                    status=status,
                    ai_task_id=task.id,
                )
            return
        token_usage = (result or {}).get("token_usage") or getattr(error, "usage", None) or {}
        await billing_recorder.record_text(
            novel_id=novel_id,
            task_type=task_type,
            model_config_id=request_params.get("model_config_id"),
            fallback_model=request_params.get("model"),
            token_usage=token_usage,
            status=status,
            ai_task_id=task.id,
        )
    except Exception:
        logger.exception("billing record failed for task %s", getattr(task, "id", None))
```

`services/ai_task_executor.py`：
- 顶部导入 `from services.billing.recorder import record_ai_task_usage`。
- `run()` 的 `except Exception as e` 分支改为 `await self._fail(task, str(e), error=e)`。
- `_fail` 签名改为 `async def _fail(self, task: AiTask, error_message: str, error: Exception | None = None)`，在 `await task.save(...)` 后加 `await record_ai_task_usage(task, result=None, error=error)`。
- `_complete` 在 `await task.save(...)` 后加 `await record_ai_task_usage(task, result=result, error=None)`。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_services/test_ai_task_executor.py test/test_services/test_billing_recorder.py -q`
Expected: PASS（既有执行器用例不因 `novel_id` 缺失而写流水，无回归）

- [ ] **Step 5: Commit**

```bash
git add controllers/chapter.py controllers/asset.py controllers/scene.py services/billing/recorder.py services/ai_task_executor.py test/test_services/test_ai_task_executor.py
git commit -m "feat(billing): 提交点补 model_config_id/novel_id 并由 executor 落流水"
```

---

### Task 7: 视频流水落点 `controllers/video.py`

**Files:**
- Modify: `controllers/video.py`（`generate` 写 `novel_id` 到 metadata；`query_status` 完成/失败落流水）
- Test: `test/test_controllers/test_video_controller.py`（新增用例）

**Interfaces:**
- Consumes: `billing_recorder`（Task 4）、`Video.metadata`（含 `model_config_id`/`resolution`/`duration`/`novel_id`）。
- Produces: 视频 `completed` 按秒计费，`failed/cancelled` 记 0。

- [ ] **Step 1: 写失败测试**

在 `test/test_controllers/test_video_controller.py` 末尾追加：

```python
from models.usage_record import ModelUsageRecord
from models.scene import Scene
from models.chapter import Chapter
from models.novel import Novel
from models.video import Video
from services.video.base import BaseVideoGenerator


class FakeCompletedGenerator:
    async def query(self, external_task_id: str) -> dict:
        return {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://example.com/v.mp4",
            "metadata": {"duration": 6},
        }


@pytest.mark.asyncio
async def test_query_status_completed_落视频流水():
    novel = await Novel.create(name="视频计费小说", author="a")
    chapter = await Chapter.create(novel_id=novel.id, number=1, name="第1章", content="c")
    scene = await Scene.create(chapter_id=chapter.id, sequence=1, description="d", prompt="p", duration=6)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video", base_url="https://ark.cn-beijing.volces.com/api/v3", api_key="k", model="v",
        api_protocol="volcengine_ark", video_model_type="seedance_2",
        pricing={"type": "video", "currency": "CNY", "prices": {"720p": 1.0}},
        is_active=True,
    )
    video = await Video.create(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="ext-1",
        status=TaskStatusEnum.pending.value,
        metadata={"model_config_id": config.id, "novel_id": novel.id, "resolution": "720p", "duration": 6},
    )
    with (
        patch("controllers.video.get_generator", return_value=FakeCompletedGenerator()),
        patch("controllers.video._download_video", new=AsyncMock(return_value="/media/videos/1.mp4")),
    ):
        await video_controller.query_status(video.id)

    record = await ModelUsageRecord.filter(video_id=video.id).first()
    assert record is not None
    assert record.billing_type == "video"
    assert record.status == TaskStatusEnum.completed.value
    assert record.cost == Decimal("6.000000")
```

（若该测试文件尚未导入 `Decimal`/`VideoModelTypeEnum`，在测试文件顶部补 `from decimal import Decimal` 与 `from utils.enums import AiTaskTypeEnum, TaskStatusEnum, VideoModelTypeEnum`。）

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_controllers/test_video_controller.py -q`
Expected: FAIL（流水未落库）

- [ ] **Step 3: 写最小实现**

`controllers/video.py`：
- `generate()` 的 `video_metadata` 加 `"novel_id": novel_id`。
- `query_status()` 在 `await video.save(update_fields=update_fields)` 之前加：

```python
        try:
            if new_status == TaskStatusEnum.completed.value:
                seconds = result_metadata.get("duration") or metadata.get("duration")
                await billing_recorder.record_video(
                    novel_id=metadata.get("novel_id"),
                    model_config_id=metadata.get("model_config_id"),
                    seconds=seconds,
                    resolution=metadata.get("resolution"),
                    status=TaskStatusEnum.completed.value,
                    video_id=video.id,
                )
            elif new_status in (TaskStatusEnum.failed.value, TaskStatusEnum.cancelled.value):
                await billing_recorder.record_video(
                    novel_id=metadata.get("novel_id"),
                    model_config_id=metadata.get("model_config_id"),
                    seconds=0.0,
                    resolution=metadata.get("resolution"),
                    status=TaskStatusEnum.failed.value,
                    video_id=video.id,
                )
        except Exception:
            logger.exception("billing record failed for video %s", video.id)
```

- 顶部导入 `from services.billing.recorder import billing_recorder`。

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_controllers/test_video_controller.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add controllers/video.py test/test_controllers/test_video_controller.py
git commit -m "feat(billing): 视频完成按秒计费、失败记零"
```

---

### Task 8: 聚合服务 `services/billing/aggregation.py`

**Files:**
- Create: `services/billing/aggregation.py`
- Test: `test/test_services/test_billing_aggregation.py`

**Interfaces:**
- Consumes: `ModelUsageRecord`、`Novel`（Task 2）。
- Produces:
  - `summary() -> dict`（键 `total_cost, total_records, by_billing_type, by_task_type, by_model, daily_trend`）
  - `project_costs(page, page_size) -> dict`（`items` + `pagination`）
  - `project_detail(novel_id) -> dict`（`novel_id, novel_name, total_cost, record_count, by_task_type`）
  - `list_records(params) -> dict`（`items` + `pagination`，items 为 ORM 实例）

- [ ] **Step 1: 写失败测试**

`test/test_services/test_billing_aggregation.py`:

```python
from decimal import Decimal

import pytest

from models.config import AiModelConfig
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from services.billing import aggregation
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.page import QueryParams


async def _seed():
    novel_a = await Novel.create(name="项目A", author="a")
    novel_b = await Novel.create(name="项目B", author="b")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm", base_url="https://x", api_key="k", model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    await ModelUsageRecord.create(
        novel_id=novel_a.id, task_type=AiTaskTypeEnum.extraction.value, billing_type="text",
        model_config_id=config.id, model_name="llm", model="m",
        pricing_snapshot=config.pricing, usage={"input_tokens": 1500, "output_tokens": 500},
        cost=Decimal("0.002500"), status=TaskStatusEnum.completed.value,
    )
    await ModelUsageRecord.create(
        novel_id=novel_a.id, task_type=AiTaskTypeEnum.storyboard.value, billing_type="text",
        model_config_id=config.id, model_name="llm", model="m",
        pricing_snapshot=config.pricing, usage={"input_tokens": 0, "output_tokens": 0},
        cost=Decimal("0.001000"), status=TaskStatusEnum.completed.value,
    )
    await ModelUsageRecord.create(
        novel_id=novel_b.id, task_type=AiTaskTypeEnum.video.value, billing_type="video",
        model="vid", usage={"seconds": 3, "resolution": "720p"},
        cost=Decimal("3.000000"), status=TaskStatusEnum.completed.value,
    )
    return novel_a, novel_b


@pytest.mark.asyncio
async def test_summary_aggregates_total_and_dimensions():
    await _seed()
    result = await aggregation.summary()
    assert result["total_records"] == 3
    assert round(result["total_cost"], 6) == 3.003500
    billing = {item["billing_type"]: item["cost"] for item in result["by_billing_type"]}
    assert billing["text"] == 0.003500
    assert billing["video"] == 3.0


@pytest.mark.asyncio
async def test_project_costs_groups_and_sorts():
    novel_a, novel_b = await _seed()
    result = await aggregation.project_costs(1, 10)
    items = result["items"]
    assert result["pagination"]["total"] == 2
    assert items[0]["novel_id"] == novel_b.id  # 3.0 > 0.0035
    assert items[0]["novel_name"] == "项目B"


@pytest.mark.asyncio
async def test_project_detail_returns_novel_cost():
    novel_a, _ = await _seed()
    result = await aggregation.project_detail(novel_a.id)
    assert result["novel_name"] == "项目A"
    assert result["record_count"] == 2
    assert round(result["total_cost"], 6) == 0.0035


@pytest.mark.asyncio
async def test_list_records_filters_by_novel():
    novel_a, novel_b = await _seed()
    params = QueryParams(page=1, page_size=10, filters={"novel_id": novel_a.id})
    result = await aggregation.list_records(params)
    assert result["pagination"]["total"] == 2
    assert all(item.novel_id == novel_a.id for item in result["items"])
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_services/test_billing_aggregation.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 写最小实现**

`services/billing/aggregation.py`:

```python
"""账单聚合：总览、项目成本、项目明细、流水分页。"""

from collections import defaultdict
from decimal import Decimal

from models.novel import Novel
from models.usage_record import ModelUsageRecord
from utils.page import QueryBuilder


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _money(value: Decimal) -> float:
    return round(float(value), 6)


async def summary() -> dict:
    rows = await ModelUsageRecord.all().values(
        "task_type", "billing_type", "model", "model_name", "cost", "created_at"
    )
    total = sum((_dec(row["cost"]) for row in rows), Decimal("0"))
    by_billing: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_task: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    by_model: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    daily: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        cost = _dec(row["cost"])
        by_billing[row["billing_type"]] += cost
        by_task[row["task_type"]] += cost
        by_model[row["model_name"] or row["model"] or "未知模型"] += cost
        daily[row["created_at"].date().isoformat()] += cost
    return {
        "total_cost": _money(total),
        "total_records": len(rows),
        "by_billing_type": [
            {"billing_type": key, "cost": _money(value)}
            for key, value in sorted(by_billing.items())
        ],
        "by_task_type": [
            {"task_type": key, "cost": _money(value)}
            for key, value in sorted(by_task.items())
        ],
        "by_model": [
            {"model": key, "cost": _money(value)}
            for key, value in sorted(by_model.items(), key=lambda item: -item[1])
        ],
        "daily_trend": [
            {"date": key, "cost": _money(value)}
            for key, value in sorted(daily.items())
        ],
    }


async def project_costs(page: int, page_size: int) -> dict:
    rows = await ModelUsageRecord.all().values("novel_id", "cost")
    agg: dict[int, dict] = defaultdict(
        lambda: {"total_cost": Decimal("0"), "record_count": 0}
    )
    for row in rows:
        novel_id = row["novel_id"]
        agg[novel_id]["total_cost"] += _dec(row["cost"])
        agg[novel_id]["record_count"] += 1
    novel_ids = list(agg.keys())
    novels = (
        {novel.id: novel.name for novel in await Novel.filter(id__in=novel_ids)}
        if novel_ids
        else {}
    )
    items = [
        {
            "novel_id": novel_id,
            "novel_name": novels.get(novel_id, "（已删除项目）"),
            "total_cost": _money(value["total_cost"]),
            "record_count": value["record_count"],
        }
        for novel_id, value in sorted(
            agg.items(), key=lambda item: -item[1]["total_cost"]
        )
    ]
    total = len(items)
    pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "pagination": {"total": total, "page": page, "page_size": page_size, "pages": pages},
    }


async def project_detail(novel_id: int) -> dict:
    novel = await Novel.get_or_none(id=novel_id)
    rows = await ModelUsageRecord.filter(novel_id=novel_id).values("task_type", "cost")
    total = sum((_dec(row["cost"]) for row in rows), Decimal("0"))
    by_task: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        by_task[row["task_type"]] += _dec(row["cost"])
    return {
        "novel_id": novel_id,
        "novel_name": novel.name if novel else "（已删除项目）",
        "total_cost": _money(total),
        "record_count": len(rows),
        "by_task_type": [
            {"task_type": key, "cost": _money(value)}
            for key, value in sorted(by_task.items())
        ],
    }


async def list_records(params) -> dict:
    query = ModelUsageRecord.all()
    query = await QueryBuilder.apply_filters(query, ModelUsageRecord, params.filters or {})
    query = query.order_by("-id")
    total = await query.count()
    query = await QueryBuilder.apply_pagination(query, params.page, params.page_size)
    items = await query
    pages = (total + params.page_size - 1) // params.page_size if total else 0
    return {
        "items": items,
        "pagination": {
            "total": total,
            "page": params.page,
            "page_size": params.page_size,
            "pages": pages,
        },
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_services/test_billing_aggregation.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/billing/aggregation.py test/test_services/test_billing_aggregation.py
git commit -m "feat(billing): 账单聚合服务（总览/项目成本/明细/流水）"
```

---

### Task 9: 计费 API（schema + controller + router）

**Files:**
- Create: `schemas/billing.py`
- Create: `controllers/billing.py`
- Create: `api/billing.py`
- Modify: `api/__init__.py`（注册 router）
- Test: `test/test_api/test_billing_api.py`

**Interfaces:**
- Consumes: `services/billing.aggregation`（Task 8）、`ResponseSchema`/`PaginationResponse`。
- Produces: 路由 `GET /api/billing/summary`、`GET /api/billing/projects`、`GET /api/billing/projects/{novel_id}`、`GET /api/billing/records`。

- [ ] **Step 1: 写失败测试**

`test/test_api/test_billing_api.py`:

```python
from decimal import Decimal

import pytest
from httpx import AsyncClient

from models.config import AiModelConfig
from models.novel import Novel
from models.usage_record import ModelUsageRecord
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


@pytest.mark.asyncio
async def test_billing_summary_endpoint(client: AsyncClient):
    novel = await Novel.create(name="计费小说", author="a")
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="llm", base_url="https://x", api_key="k", model="m",
        pricing={"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0},
    )
    await ModelUsageRecord.create(
        novel_id=novel.id, task_type=AiTaskTypeEnum.extraction.value, billing_type="text",
        model_config_id=config.id, model_name="llm", model="m",
        usage={"input_tokens": 1500, "output_tokens": 500},
        cost=Decimal("0.002500"), status=TaskStatusEnum.completed.value,
    )

    response = await client.get("/api/billing/summary")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_records"] == 1
    assert data["total_cost"] == 0.0025


@pytest.mark.asyncio
async def test_billing_projects_and_records(client: AsyncClient):
    novel = await Novel.create(name="项目甲", author="a")
    await ModelUsageRecord.create(
        novel_id=novel.id, task_type=AiTaskTypeEnum.video.value, billing_type="video",
        model="vid", usage={"seconds": 3, "resolution": "720p"},
        cost=Decimal("3.000000"), status=TaskStatusEnum.completed.value,
    )

    projects = await client.get("/api/billing/projects")
    assert projects.status_code == 200
    items = projects.json()["data"]["items"]
    assert items[0]["novel_name"] == "项目甲"
    assert items[0]["total_cost"] == 3.0

    records = await client.get(f"/api/billing/records?novel_id={novel.id}")
    assert records.status_code == 200
    assert records.json()["data"]["pagination"]["total"] == 1
    assert records.json()["data"]["items"][0]["billing_type"] == "video"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_api/test_billing_api.py -q`
Expected: FAIL（404 / 路由不存在）

- [ ] **Step 3: 写最小实现**

`schemas/billing.py`:

```python
"""账单计费相关 schema。"""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from schemas._base import BaseResponse


class ModelUsageRecordOut(BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: int
    novel_id: int
    task_type: int
    billing_type: str
    ai_task_id: Optional[str] = None
    video_id: Optional[int] = None
    model_config_id: Optional[int] = None
    model_name: Optional[str] = None
    model: str
    model_type: Optional[str] = None
    pricing_snapshot: Optional[dict] = None
    usage: dict
    cost: float
    currency: str
    status: int


class BillingSummaryOut(BaseModel):
    total_cost: float
    total_records: int
    by_billing_type: list[dict]
    by_task_type: list[dict]
    by_model: list[dict]
    daily_trend: list[dict]


class BillingProjectOut(BaseModel):
    novel_id: int
    novel_name: str
    total_cost: float
    record_count: int


class BillingProjectDetailOut(BaseModel):
    novel_id: int
    novel_name: str
    total_cost: float
    record_count: int
    by_task_type: list[dict]
```

`controllers/billing.py`:

```python
"""账单计费控制器。"""

from services.billing import aggregation


class BillingController:
    async def summary(self) -> dict:
        return await aggregation.summary()

    async def projects(self, page: int, page_size: int) -> dict:
        return await aggregation.project_costs(page, page_size)

    async def project_detail(self, novel_id: int) -> dict:
        return await aggregation.project_detail(novel_id)

    async def records(self, params) -> dict:
        return await aggregation.list_records(params)


billing_controller = BillingController()
```

`api/billing.py`:

```python
from fastapi import APIRouter, Depends

from controllers.billing import billing_controller
from schemas.billing import (
    BillingProjectDetailOut,
    BillingProjectOut,
    BillingSummaryOut,
    ModelUsageRecordOut,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.get("/summary", summary="账单汇总", response_model=ResponseSchema[BillingSummaryOut])
async def get_billing_summary():
    return ResponseSchema(data=await billing_controller.summary())


@router.get(
    "/projects",
    summary="项目成本列表",
    response_model=ResponseSchema[PaginationResponse[BillingProjectOut]],
)
async def get_billing_projects(params: QueryParams = Depends(get_list_params)):
    return ResponseSchema(data=await billing_controller.projects(params.page, params.page_size))


@router.get(
    "/projects/{novel_id}",
    summary="单项目成本明细",
    response_model=ResponseSchema[BillingProjectDetailOut],
)
async def get_billing_project_detail(novel_id: int):
    return ResponseSchema(data=await billing_controller.project_detail(novel_id))


@router.get(
    "/records",
    summary="计费流水列表",
    response_model=ResponseSchema[PaginationResponse[ModelUsageRecordOut]],
)
async def get_billing_records(params: QueryParams = Depends(get_list_params)):
    return ResponseSchema(data=await billing_controller.records(params))
```

`api/__init__.py`：加 `from api.billing import router as billing_router`，并注册：

```python
api_router.include_router(billing_router, prefix="/billing", tags=["账单计费"])
```

- [ ] **Step 4: 运行确认通过**

Run: `uv run pytest test/test_api/test_billing_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add schemas/billing.py controllers/billing.py api/billing.py api/__init__.py test/test_api/test_billing_api.py
git commit -m "feat(billing): 账单汇总/项目成本/流水查询 API"
```

---

### Task 10: 前端 —— 模型配置页费用编辑区

**Files:**
- Modify: `controllers/config.py`（`list_generation_capabilities`）
- Modify: `api/config.py`（`/generation/capabilities` 路由）
- Modify: `web/src/types.ts`（`ModelPricing`、`GenerationCapabilities`、`AiModelConfig.pricing`）
- Modify: `web/src/api.ts`（`generationCapabilities`）
- Create: `web/src/shared/modelPricing.ts`
- Test: `web/src/shared/modelPricing.test.ts`
- Modify: `web/src/pages/ConfigPage.vue`（费用编辑区 + payload 带 pricing）

**Interfaces:**
- Consumes: `image_capabilities_for` / `video_capabilities_for`（后端）；`api.generationCapabilities()`（前端）。
- Produces: `GET /api/config/generation/capabilities` 返回 `{image: {model_type: [clarities]}, video: {model_type: [resolutions]}}`；`shared/modelPricing.ts` 的 `defaultPricing` / `pricingTiers`。

- [ ] **Step 1: 写失败测试（后端）**

在 `test/test_controllers/test_config_controller.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_list_generation_capabilities_returns_all_types():
    capabilities = await ai_model_config_controller.list_generation_capabilities()
    assert "1K" in capabilities["image"]["seedream_5_pro"]
    assert "720p" in capabilities["video"]["seedance_2"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest test/test_controllers/test_config_controller.py::test_list_generation_capabilities_returns_all_types -q`
Expected: FAIL（`AttributeError`）

- [ ] **Step 3: 写后端实现**

`controllers/config.py` 顶部导入改为：

```python
from utils.enums import AiTaskTypeEnum, ImageModelTypeEnum, VideoGenerationModelTypeEnum
```

类内加方法：

```python
    async def list_generation_capabilities(self) -> dict:
        return {
            "image": {
                model_type.value: list(image_capabilities_for(model_type.value).clarities)
                for model_type in ImageModelTypeEnum
            },
            "video": {
                model_type.value: list(video_capabilities_for(model_type.value).resolutions)
                for model_type in VideoGenerationModelTypeEnum
            },
        }
```

`api/config.py` 加路由（放在 `get_video_generation_models` 之后）：

```python
@router.get("/generation/capabilities", summary="获取各模型类型的清晰度/分辨率档位", response_model=ResponseSchema)
async def get_generation_capabilities():
    return ResponseSchema(data=await ai_model_config_controller.list_generation_capabilities())
```

- [ ] **Step 4: 运行确认通过（后端）**

Run: `uv run pytest test/test_controllers/test_config_controller.py -q`
Expected: PASS

- [ ] **Step 5: 写失败测试（前端）**

`web/src/shared/modelPricing.ts`:

```ts
import type { ModelPricing } from '@/types'

export function defaultPricing(category: 'llm' | 'image' | 'video', tiers: string[] = []): ModelPricing {
  if (category === 'llm') {
    return { type: 'text', currency: 'CNY', input_price_per_1m: 0, output_price_per_1m: 0 }
  }
  const prices: Record<string, number> = {}
  tiers.forEach(tier => { prices[tier] = 0 })
  return { type: category === 'image' ? 'image' : 'video', currency: 'CNY', prices }
}

export function pricingTiers(pricing: ModelPricing | null | undefined): string[] {
  return pricing?.prices ? Object.keys(pricing.prices) : []
}
```

`web/src/shared/modelPricing.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { defaultPricing, pricingTiers } from './modelPricing'

describe('modelPricing', () => {
  it('文本模型默认定价结构', () => {
    expect(defaultPricing('llm')).toEqual({
      type: 'text', currency: 'CNY', input_price_per_1m: 0, output_price_per_1m: 0,
    })
  })
  it('图片模型按档位生成价格对象', () => {
    expect(defaultPricing('image', ['1K', '2K']).prices).toEqual({ '1K': 0, '2K': 0 })
  })
  it('pricingTiers 提取档位列表', () => {
    expect(pricingTiers({ type: 'image', currency: 'CNY', prices: { '1K': 0.1 } })).toEqual(['1K'])
    expect(pricingTiers(null)).toEqual([])
  })
})
```

- [ ] **Step 6: 运行确认失败（前端）**

Run: `cd web && npm run test -- modelPricing`
Expected: FAIL（模块不存在）

- [ ] **Step 7: 写前端实现**

`web/src/types.ts` 加：

```ts
export interface ModelPricing {
  type: 'text' | 'image' | 'video'
  currency: string
  input_price_per_1m?: number
  output_price_per_1m?: number
  prices?: Record<string, number>
}
export interface GenerationCapabilities { image: Record<string, string[]>; video: Record<string, string[]> }
```

并把 `AiModelConfig` 接口加 `pricing?: ModelPricing | null`。

`web/src/api.ts` 加：

```ts
  generationCapabilities: () => request<SingleResponse<GenerationCapabilities>>('/config/generation/capabilities'),
```

（在 `import type {...}` 里补 `GenerationCapabilities, ModelPricing`。）

`web/src/pages/ConfigPage.vue`：
- 引入 `defaultPricing`、`pricingTiers` 与 `ModelPricing` 类型。
- `form` 增加 `pricing: null as ModelPricing | null`。
- 加 `const generationCapabilities = ref<GenerationCapabilities>({ image: {}, video: {} })`，`load()` 里 `Promise.all` 追加 `api.generationCapabilities()` 并赋值。
- 加计算属性 `pricingTierOptions`：`selectedCategoryId === 'image'` 时取 `generationCapabilities.value.image[form.value.image_model_type] || []`；`video` 时取 `video[...]`；否则 `[]`。
- `openCreate`/`openEdit` 里初始化 `form.pricing = item.pricing ?? defaultPricing(category.id, tiersFor(category))`（编辑时用 `item.pricing`，创建时 `null`）。
- 在 modal 的表单区新增费用编辑块：

```vue
<section v-if="selectedCategoryId !== 'llm' && pricingTierOptions.length" class="pricing-editor is-full">
  <span class="pricing-title">费用设置（元）</span>
  <label v-for="tier in pricingTierOptions" :key="tier">
    <span>{{ selectedCategoryId === 'image' ? '清晰度' : '分辨率' }} {{ tier }}</span>
    <input v-model.number="tierPrices[tier]" type="number" min="0" step="0.01" />
    <small>{{ selectedCategoryId === 'image' ? '元 / 张' : '元 / 秒' }}</small>
  </label>
</section>
<section v-else-if="selectedCategoryId === 'llm'" class="pricing-editor is-full">
  <span class="pricing-title">费用设置（元 / 百万 token）</span>
  <label><span>输入单价</span><input v-model.number="textPricing.input_price_per_1m" type="number" min="0" step="0.01" /></label>
  <label><span>输出单价</span><input v-model.number="textPricing.output_price_per_1m" type="number" min="0" step="0.01" /></label>
</section>
```

- 加 `const textPricing = ref({ input_price_per_1m: 0, output_price_per_1m: 0 })` 与 `const tierPrices = ref<Record<string, number>>({})`；在 `openCreate`/`openEdit` 里根据 `item.pricing` 同步这两个 ref。
- `saveConfig` 构造 payload 时组装 `pricing`：

```ts
const pricing = selectedCategoryId.value === 'llm'
  ? { type: 'text', currency: 'CNY', ...textPricing.value }
  : { type: selectedCategoryId.value === 'image' ? 'image' : 'video', currency: 'CNY', prices: { ...tierPrices.value } }
payload.pricing = pricing
```

- 在 `<style scoped>` 末尾补 `.pricing-editor` 基础样式（`display:grid; gap:10px; grid-column:1/-1; padding:14px; border:1px solid var(--app-border); border-radius:12px;`，内部 label 沿用 `.model-form-grid label` 布局）。精确样式由实现者按现有 `.model-form-grid` 视觉对齐即可。

- [ ] **Step 8: 运行确认通过（前端）**

Run: `cd web && npm run test -- modelPricing && npm run typecheck`
Expected: PASS（typecheck 无错误）

- [ ] **Step 9: Commit**

```bash
git add controllers/config.py api/config.py web/src/types.ts web/src/api.ts web/src/shared/modelPricing.ts web/src/shared/modelPricing.test.ts web/src/pages/ConfigPage.vue test/test_controllers/test_config_controller.py
git commit -m "feat(billing): 模型配置页费用编辑区与档位能力接口"
```

---

### Task 11: 前端 —— 成本看板 `BillingPage`

**Files:**
- Modify: `web/src/types.ts`（`BillingRecord`、`BillingSummary`、`BillingProject`、`BillingProjectDetail`）
- Modify: `web/src/api.ts`（计费请求封装）
- Modify: `web/src/router.ts`（`/billing` 路由）
- Modify: `web/src/App.vue`（导航入口）
- Create: `web/src/pages/BillingPage.vue`
- Test: `web/src/pages/BillingPage.spec.ts`

**Interfaces:**
- Consumes: 后端 `/api/billing/*`（Task 9）、`statusLabel`、`api`。
- Produces: `/billing` 页面（汇总卡片 + 项目成本表 + 流水表）。

- [ ] **Step 1: 写失败测试**

`web/src/pages/BillingPage.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { api } from '@/api'
import BillingPage from './BillingPage.vue'

vi.mock('@/api', () => ({
  api: {
    billingSummary: vi.fn(),
    billingProjects: vi.fn(),
    billingRecords: vi.fn(),
  },
  statusLabel: vi.fn((status?: number) => (status ? String(status) : '未知')),
}))

describe('BillingPage', () => {
  it('渲染汇总卡片与项目成本表', async () => {
    vi.mocked(api.billingSummary).mockResolvedValue({
      code: 0, message: 'ok',
      data: { total_cost: 3.0035, total_records: 3, by_billing_type: [], by_task_type: [], by_model: [], daily_trend: [] },
    })
    vi.mocked(api.billingProjects).mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [{ novel_id: 1, novel_name: '项目A', total_cost: 3.0035, record_count: 3 }], pagination: { total: 1, page: 1, page_size: 20, pages: 1 } },
    })
    vi.mocked(api.billingRecords).mockResolvedValue({
      code: 0, message: 'ok',
      data: { items: [], pagination: { total: 0, page: 1, page_size: 20, pages: 0 } },
    })

    const wrapper = mount(BillingPage, { global: { stubs: { RouterLink: true } } })
    await flushPromises()

    expect(wrapper.text()).toContain('总成本')
    expect(wrapper.text()).toContain('项目A')
    expect(wrapper.text()).toContain('3.0035')
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd web && npm run test -- BillingPage`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 写前端实现**

`web/src/types.ts` 追加：

```ts
export interface BillingRecord {
  id: number
  novel_id: number
  task_type: number
  billing_type: 'text' | 'image' | 'video'
  ai_task_id?: string | null
  video_id?: number | null
  model_config_id?: number | null
  model_name?: string | null
  model: string
  model_type?: string | null
  pricing_snapshot?: Record<string, unknown> | null
  usage: Record<string, unknown>
  cost: number
  currency: string
  status: number
  created_at: string
  updated_at: string
}
export interface BillingSummary {
  total_cost: number
  total_records: number
  by_billing_type: Array<{ billing_type: string; cost: number }>
  by_task_type: Array<{ task_type: number; cost: number }>
  by_model: Array<{ model: string; cost: number }>
  daily_trend: Array<{ date: string; cost: number }>
}
export interface BillingProject { novel_id: number; novel_name: string; total_cost: number; record_count: number }
export interface BillingProjectDetail {
  novel_id: number
  novel_name: string
  total_cost: number
  record_count: number
  by_task_type: Array<{ task_type: number; cost: number }>
}
```

`web/src/api.ts` 加（并在 import type 里补 `BillingProject, BillingProjectDetail, BillingRecord, BillingSummary`）：

```ts
  billingSummary: () => request<SingleResponse<BillingSummary>>('/billing/summary'),
  billingProjects: (page = 1, pageSize = 20) => request<PaginationResponse<BillingProject>>(`/billing/projects${qs({ page, page_size: pageSize })}`),
  billingProject: (id: number) => request<SingleResponse<BillingProjectDetail>>(`/billing/projects/${id}`),
  billingRecords: (params: { novel_id?: number; task_type?: number; billing_type?: string; status?: number; page?: number; page_size?: number } = {}) => request<PaginationResponse<BillingRecord>>(`/billing/records${qs(params)}`),
```

`web/src/router.ts` 加：

```ts
    { path: '/billing', component: () => import('./pages/BillingPage.vue') },
```

`web/src/App.vue`：导入 `BarChart3`，在 `personalItems` 加：

```ts
  { path: '/billing', label: '成本', icon: BarChart3, active: () => route.path.startsWith('/billing') },
```

`web/src/pages/BillingPage.vue`（完整实现，含汇总卡片、按维度拆解、项目成本表、流水表与分页）：

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { BarChart3, Coins, ListOrdered } from 'lucide-vue-next'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { statusLabel } from '@/api'
import type { BillingProject, BillingRecord, BillingSummary } from '@/types'

const summary = ref<BillingSummary | null>(null)
const projects = ref<BillingProject[]>([])
const records = ref<BillingRecord[]>([])
const totalRecords = ref(0)
const loading = ref(true)
const page = ref(1)
const pageSize = 20

const billingTypeLabel = (value: string) => ({ text: '文本', image: '生图', video: '视频' }[value] || value)
const taskTypeLabel = (value: number) => ({ 1: '提取', 2: '参考图', 3: '分镜', 4: '视频', 5: '项目分析' }[value] || `任务 ${value}`)
const money = (value: number) => `¥ ${value.toFixed(6)}`

async function load() {
  loading.value = true
  try {
    const [summaryResponse, projectsResponse, recordsResponse] = await Promise.all([
      api.billingSummary(),
      api.billingProjects(1, 100),
      api.billingRecords({ page: page.value, page_size: pageSize }),
    ])
    summary.value = summaryResponse.data
    projects.value = projectsResponse.data.items
    records.value = recordsResponse.data.items
    totalRecords.value = recordsResponse.data.pagination.total
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function changePage(next: number) {
  page.value = next
  await load()
}

onMounted(load)
</script>

<template>
  <main class="billing-page">
    <header class="billing-header">
      <span>COST DASHBOARD</span>
      <h1>成本看板</h1>
      <p>每个模型的调用成本，按项目与维度汇总。</p>
    </header>

    <div v-if="loading" class="billing-state">正在读取成本数据…</div>
    <template v-else>
      <section class="summary-grid">
        <article class="summary-card">
          <Coins :size="20" />
          <span>总成本</span>
          <strong>{{ summary ? money(summary.total_cost) : '¥ 0.000000' }}</strong>
        </article>
        <article class="summary-card">
          <ListOrdered :size="20" />
          <span>调用次数</span>
          <strong>{{ summary?.total_records ?? 0 }}</strong>
        </article>
        <article class="summary-card">
          <BarChart3 :size="20" />
          <span>计费维度</span>
          <ul>
            <li v-for="item in summary?.by_billing_type ?? []" :key="item.billing_type">
              {{ billingTypeLabel(item.billing_type) }} · {{ money(item.cost) }}
            </li>
          </ul>
        </article>
      </section>

      <section class="panel">
        <header><h2>项目成本</h2></header>
        <table class="data-table">
          <thead><tr><th>项目</th><th>调用次数</th><th>成本</th></tr></thead>
          <tbody>
            <tr v-for="item in projects" :key="item.novel_id">
              <td>{{ item.novel_name }}</td>
              <td>{{ item.record_count }}</td>
              <td>{{ money(item.total_cost) }}</td>
            </tr>
            <tr v-if="!projects.length"><td colspan="3" class="empty">暂无计费数据</td></tr>
          </tbody>
        </table>
      </section>

      <section class="panel">
        <header><h2>调用流水</h2></header>
        <table class="data-table">
          <thead><tr><th>时间</th><th>维度</th><th>任务</th><th>模型</th><th>状态</th><th>成本</th></tr></thead>
          <tbody>
            <tr v-for="item in records" :key="item.id">
              <td>{{ item.created_at }}</td>
              <td>{{ billingTypeLabel(item.billing_type) }}</td>
              <td>{{ taskTypeLabel(item.task_type) }}</td>
              <td>{{ item.model_name || item.model }}</td>
              <td>{{ statusLabel(item.status) }}</td>
              <td>{{ money(item.cost) }}</td>
            </tr>
            <tr v-if="!records.length"><td colspan="6" class="empty">暂无调用记录</td></tr>
          </tbody>
        </table>
        <footer v-if="totalRecords > pageSize" class="pager">
          <button type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span>{{ page }} / {{ Math.ceil(totalRecords / pageSize) }}</span>
          <button type="button" :disabled="page >= Math.ceil(totalRecords / pageSize)" @click="changePage(page + 1)">下一页</button>
        </footer>
      </section>
    </template>
  </main>
</template>

<style scoped>
.billing-page { min-height: 100%; padding: 36px 22px 80px; color: var(--app-text); background: var(--app-surface); }
.billing-header { margin-bottom: 28px; padding-bottom: 28px; border-bottom: 1px solid var(--app-border); }
.billing-header span { color: var(--app-accent); font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.billing-header h1 { margin: 4px 0 0; font-size: 30px; letter-spacing: -.03em; }
.billing-header p { margin: 4px 0 0; color: var(--app-text-muted); font-size: 12px; }
.billing-state { padding: 60px 0; color: var(--app-text-muted); text-align: center; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 24px; }
.summary-card { display: grid; gap: 6px; padding: 18px; border: 1px solid var(--app-border); border-radius: 14px; background: var(--app-surface-muted); }
.summary-card > svg { color: var(--app-accent); }
.summary-card span { color: var(--app-text-muted); font-size: 11px; }
.summary-card strong { font-size: 22px; }
.summary-card ul { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; color: var(--app-text-secondary); font-size: 11px; }
.panel { margin-bottom: 24px; border: 1px solid var(--app-border); border-radius: 14px; overflow: hidden; }
.panel > header { padding: 14px 18px; border-bottom: 1px solid var(--app-border); }
.panel h2 { margin: 0; font-size: 14px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th, .data-table td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--app-border); }
.data-table th { color: var(--app-text-muted); font-weight: 600; font-size: 10px; }
.data-table .empty { color: var(--app-text-muted); text-align: center; padding: 24px; }
.pager { display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 12px 18px; }
.pager button { padding: 6px 12px; border: 1px solid var(--app-border); border-radius: 8px; background: var(--app-surface-muted); cursor: pointer; }
.pager button:disabled { opacity: .5; cursor: not-allowed; }
@media (max-width: 720px) { .summary-grid { grid-template-columns: 1fr; } }
</style>
```

- [ ] **Step 4: 运行确认通过（前端）**

Run: `cd web && npm run test -- BillingPage && npm run typecheck && npm run build`
Expected: PASS（测试通过、类型检查与构建无错误）

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/api.ts web/src/router.ts web/src/App.vue web/src/pages/BillingPage.vue web/src/pages/BillingPage.spec.ts
git commit -m "feat(billing): 成本看板页与导航入口"
```

---

## 收尾验证（全部任务完成后）

```bash
# 后端全量
uv run pytest -q
# 前端全量
cd web && npm run test && npm run typecheck && npm run build
```

预期：后端既有用例与新计费用例全部通过；前端 Vitest、`tsc`、`vite build` 全部通过。
