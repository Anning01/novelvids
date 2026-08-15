# 账单计费模块设计（Billing & Cost Tracking）

## 目标（Goal）

为每一次 AI 模型调用建立可审计的计费记录，为每个项目（小说）提供成本计算，并从「模型」维度为模型配置可自定义的计费费用模块。

- **每次模型调用都有记录**：调用级流水，一次任务可能产生多条流水（例如项目分析 = 文本 + 生图）。
- **每个项目都有成本**：项目成本 = 该项目（`novel_id`）下所有计费流水的 `cost` 之和。
- **模型可配置费用模块**：`AiModelConfig` 增加 `pricing` 字段，按任务类型分文本 / 图片 / 视频三种计费结构。

## 关键决策（已与用户确认）

1. **计费粒度**：按官方维度分档 —— 文本按「输入/输出 token 单价」，图片按「清晰度档位 × 张」，视频按「分辨率档位 × 秒」。
2. **界面范围**：模型配置页加费用设置 + 新增成本看板页。
3. **失败口径**：文本按实际 token 计费（即使下游解析失败，只要拿到 completion）；图片/视频仅成功计费，失败记 0。
4. **币种**：统一人民币「元」（`CNY`），不做多币种。
5. **历史数据**：上线前的旧 `AiTask` / `Video` 无 pricing/usage，成本一律 0（未计费），不回填。
6. **项目 = 小说**（`Novel`）。

## 现状（Current state）

- `AiModelConfig`（`models/config.py`）只有连接配置（base_url/api_key/model/protocol/model_type 等），无定价字段。
- 文本/图片/项目分析调用记录在 `AiTask`（`models/ai_task.py`），`request_params` 里是**扁平化**配置（无 `config_id`），带 `novel_id`/`chapter_id`/`asset_id`。
- 视频调用**不走 `AiTask`**，走 `Video` 表（`controllers/video.py`：`submit` → 轮询 `query_status`）。
- token 用量目前只有**分镜**抓了（`metadata.usage`）；提取（`AssetExtractor.extract`）与项目分析都把 `completion.usage` 丢弃。
- 迁移机制：`Tortoise.generate_schemas(safe=True)` 自动建新表；已有表加列走 `services/schema_compat.py` 的 SQLite `ALTER TABLE`。

## 数据模型（Data model）

### `AiModelConfig.pricing`（JSONField，可空）

按配置的任务类型分三种结构，`type` 由配置的 `task_types` 归属类别决定：

- 文本（extraction / storyboard / project_analysis）：
  ```json
  {"type": "text", "currency": "CNY", "input_price_per_1m": 1.0, "output_price_per_1m": 2.0}
  ```
- 图片（reference_image）：
  ```json
  {"type": "image", "currency": "CNY", "prices": {"1K": 0.10, "2K": 0.20}}
  ```
  key 为清晰度档位（Seedream `1K/1.5K/2K/3K/4K`，GPT Image `low/medium/high`），取值来自 `image_model_type` 的 capabilities（`services/image_generation/capabilities.py`）。
- 视频（video）：
  ```json
  {"type": "video", "currency": "CNY", "prices": {"480p": 0.50, "720p": 1.00}}
  ```
  key 为分辨率档位，来自 `video_model_type` 的 capabilities（`services/video/capabilities.py`）。

### 新表 `ModelUsageRecord`（`models/usage_record.py`，表 `model_usage_records`）

一行 = 一次可计费调用。继承 `AbstractBaseModel`（含 `id`/`created_at`/`updated_at`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `novel_id` | IntField(db_index) | 项目归属 |
| `task_type` | IntField(db_index) | `AiTaskTypeEnum` |
| `billing_type` | CharField | 计费维度：`text` / `image` / `video`（用于跨任务类型的维度汇总；项目分析会落 `text` + `image` 两条） |
| `ai_task_id` | UUIDField(null) | 回溯到 `AiTask` |
| `video_id` | IntField(null) | 回溯到 `Video` |
| `model_config_id` | IntField(null) | 配置快照 |
| `model_name` | CharField(null) | 配置名快照 |
| `model` | CharField | 供应商模型 ID 快照 |
| `model_type` | CharField(null) | 图片/视频能力类型快照 |
| `pricing_snapshot` | JSONField(null) | 调用时刻的定价 JSON（改价后历史不变） |
| `usage` | JSONField(default=dict) | 文本 `{input_tokens, output_tokens}` / 图片 `{image_count, clarity}` / 视频 `{seconds, resolution}` |
| `cost` | DecimalField(max_digits=18, decimal_places=6, default=0) | 金额（元） |
| `currency` | CharField(default="CNY") | 币种 |
| `status` | IntField | `TaskStatusEnum`（completed/failed） |

新模型登记进 `models/__init__.py` 的 `__all__`（`main.py` 通过它发现模型）。

## 计费规则（Pricing rules）

金额用 `decimal.Decimal` 计算，存储四舍五入到 6 位小数（`ROUND_HALF_UP`），展示精度由前端控制。

- **文本**：`cost = input_tokens/1_000_000 × input_price_per_1m + output_tokens/1_000_000 × output_price_per_1m`。
  - token key 归一化：`prompt_tokens → input_tokens`、`completion_tokens → output_tokens`（兼容现有分镜 usage 的命名）。
  - 只要拿到 completion 就按实际 token 计（含下游解析失败时透出的 usage）；供应商调用失败（无 completion）记 0。
- **图片**：`cost = image_count × prices[clarity]`；仅成功计费，失败记 0。
- **视频**：`cost = 秒数 × prices[resolution]`（秒数取供应商返回的 `duration`）；仅成功计费，失败记 0。
- **缺定价 / 档位缺失**：`cost = 0`，仍落记录（`pricing_snapshot = null`），便于审计。
- **写库容错**：计费流水写库一律 `try/except + log`，绝不因计费失败打断生成主流程。

## 埋点改造（Instrumentation）

### 提交点补 `model_config_id`（并补 `novel_id`）

- `controllers/chapter.py`（提取）：加 `model_config_id`（`novel_id` 已存在）。
- `controllers/asset.py`（参考图）：加 `model_config_id`（`novel_id` 已存在）。
- `controllers/scene.py`（分镜）：加 `model_config_id` 与 `novel_id`（`chapter.novel_id`）。
- `controllers/novel.py`（项目分析）：加 `model_config_id`（`novel_id` 已存在）。
- 视频已存 `video.metadata["model_config_id"]`，无需改动。

### usage 透出

统一约定：handler 的 `execute` 结果字典携带计费所需的用量键，由 executor 统一读取落流水。

- **分镜**：已返回 `token_usage`（`api_metadata.get("usage")`），复用。
- **提取**：`AssetExtractor.extract` 改为把 `completion.usage` 随结果返回；handler 结果加 `token_usage`。
- **项目分析**：捕获文本 `completion.usage`（结果加 `token_usage`）+ 封面生图（结果加 `image_usage = {image_count, clarity}`），executor 分别落文本、图片两条流水。
- 文本失败但已有 completion 时，usage 通过异常附带或结果透出，使失败任务仍记 token 花费。

### 落点

- `AiTaskExecutor._complete` / `_fail`：调用计费 recorder，按 `task_type` 落文本 / 图片流水（文本失败按透出的 usage 计，图片失败记 0）。
- `VideoController.query_status`：`completed` 写视频流水（计费），`failed/expired/cancelled` 写视频流水（记 0）。

## 服务与接口（Services & API）

### 服务 `services/billing/`

- `pricing.py`：定价解析（`pricing_for(config, dimension)`）+ 成本计算（`compute_text_cost` / `compute_image_cost` / `compute_video_cost`）。
- `recorder.py`：`record_text(...)` / `record_image(...)` / `record_video(...)`，含 `model_config_id` → pricing 快照查找（config 缺失则快照 null）。
- `aggregation.py`：项目成本、按任务类型/模型/日聚合。

### API

新增 `api/billing.py` + `controllers/billing.py` + `schemas/billing.py`，注册进 `api/__init__.py`：

- `GET /api/billing/summary` — 全局：总成本、按计费维度（文本/图片/视频）、按任务类型、按模型、按日趋势。
- `GET /api/billing/projects` — 项目成本列表（按成本降序、分页）。
- `GET /api/billing/projects/{novel_id}` — 单项目：总成本 + 按任务类型拆解 + 流水。
- `GET /api/billing/records` — 原始流水（按 novel_id/task_type/status/时间过滤、分页）。

`pricing` 字段并入现有 `AiModelConfig` 的 create/update/patch/out schema，并在 controller 里做类型与档位校验（复用 image/video capabilities 的清晰度/分辨率列表）。

## 前端（Frontend）

- `ConfigPage.vue`：每个模型配置加「费用」编辑区，按任务类型渲染 —— 文本=输入/输出单价两个输入框；图片=清晰度→元/张表；视频=分辨率→元/秒表。档位选项复用 capabilities（现有 `list_active_image_models` / `list_active_video_models` 已返回）。
- 新增 `BillingPage.vue`（路由 `/billing` + 导航入口）：汇总卡片、项目成本表、流水表（复用现有 `Pagination` / `AppBadge` 等组件）。
- `src/api.ts` 增加计费相关类型与请求封装。

## 迁移（Migration）

- 新表 `model_usage_records` 由 `generate_schemas(safe=True)` 自动建。
- `ai_model_configs.pricing` 列加入 `services/schema_compat.py::ensure_ai_model_config_schema`（SQLite `ALTER TABLE ADD COLUMN pricing JSON`）。
- 新模型登记进 `models/__init__.py`。

## 测试（Tests）

- 定价解析与成本计算：文本/图片/视频、四舍五入、缺档位 / 缺定价 → 0。
- usage 透出：提取、项目分析返回 `token_usage` / `image_usage`。
- executor 完整/失败落流水（文本成功计费、文本失败透出 usage、图片失败记 0）。
- 视频 controller：completed 计费、failed 记 0。
- 聚合接口：summary / projects / project detail / records。
- 前端：定价表单渲染（文本/图片/视频三种）、成本看板渲染。

## 非目标（Non-goals）

- 不做多币种 / 汇率换算。
- 不做端到端用户充值、余额、扣费（面向用户自身的成本核算，非对最终用户收费）。
- 不回填历史 `AiTask` / `Video` 的成本。
- 不引入数据库迁移框架（沿用 `generate_schemas(safe=True)` + `schema_compat.py`）。
- 不改变现有生成主流程的行为与接口契约（计费为旁路副作用）。
