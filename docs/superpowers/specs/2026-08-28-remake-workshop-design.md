# 重制工坊 P0 设计规格与验收契约

> 日期：2026-08-28
> 状态：P0 待人工验收
> 上位计划：`docs/superpowers/plans/2026-08-28-remake-workshop-phased-development-plan.md`
> 参考实现：`/Users/anning/PycharmProjects/shengshimedia` 的无限画布复刻功能

## 1. 本规格的作用

本文冻结重制工坊的第一版范围、数据职责、API、状态机、错误码、页面状态、模型调用与计费边界，以及后续各阶段的 TDD 顺序。P1 开始后，若需要改变本文中的数据归属、接口语义、依赖或计费行为，必须先回到阶段验收点说明影响。

P0 只交付设计和可执行验收规格，不修改数据库、运行时代码、依赖或锁文件。

## 2. 第一版范围

### 2.1 包含

- 在“创作”中新增“重制工坊”入口和 `/create/remake` 页面。
- 三种来源：单视频、文件夹多集、历史项目章节成片。
- MP4/MOV，单文件不超过 500MiB，时长不超过 20 分钟。
- 文件夹文件名识别集数、排序、重复校验和断集警告。
- 项目级比例、清晰度、系统风格或自定义风格。
- 每个来源视频对应一集，自动拆出人物、场景、道具和分镜。
- 无限画布展示来源、拆解进度、设定、分镜、生成版本和成片合成。
- 拆解任务刷新可恢复、失败可重试、单集相互隔离。
- 历史来源生成不可变视频快照。

### 2.2 不包含

- 不复制 `shengshimedia` 的通用图数据库、工作区版本表和分享/模板能力。
- 不增加商品节点。
- 不增加真人数字人类型。
- 不在创建项目后自动生成设定图、镜头视频或最终成片。
- 不允许混合来源创建：一次创建请求只能是单视频、文件夹或历史项目中的一种。
- 不提供视频编辑时间线、字幕编辑、配音重制和音轨分离。
- 不允许创建后替换已经绑定的来源媒体；需要换源时新建项目。

## 3. 权威数据职责

```text
Novel（项目与生成默认值）
  └─ Chapter（目标集）
      └─ RemakeSource（该集不可变来源）
          └─ AiTask（当前拆解任务）

RemakeUpload（创建前暂存，成功绑定后不可再次使用）
```

- `Novel/Chapter/Asset/Scene/Video` 继续是业务事实来源。
- `RemakeUpload` 只管理创建前媒体暂存和所有权，不参与画布业务。
- `RemakeSource` 管理提交后的不可变来源及来源审计。
- `AiTask` 管理异步拆解状态，不另建任务状态表。
- `source_video` 和 `ai_decomposition` 是服务端业务数据派生的画布节点，不另行持久化图数据。

## 4. 数据模型冻结

### 4.1 Novel 增量字段

| 字段 | 类型 | 默认/约束 | 职责 |
| --- | --- | --- | --- |
| `workflow_kind` | `VARCHAR(32)` | 非空，默认 `script`，索引 | `script` 或 `remake`；旧项目回填 `script` |
| `aspect_ratio` | `VARCHAR(16)` | 可空 | 项目默认比例；重制项目创建时必填 |
| `resolution` | `VARCHAR(32)` | 可空 | 项目默认视频清晰度；重制项目创建时必填 |
| `custom_style_prompt` | `TEXT` | 可空 | 自定义风格文本；与 `style_key` 二选一 |
| `creation_idempotency_key` | `VARCHAR(64)` | 可空、唯一 | 重制创建请求幂等键；普通项目为空 |
| `creation_payload_hash` | `VARCHAR(64)` | 可空 | 规范化创建请求的 SHA-256，用于识别同 key 不同 payload |

固定规则：

- `workflow_kind=remake` 时，`aspect_ratio`、`resolution` 必填。
- `style_key` 与 `custom_style_prompt` 必须且只能填写一个。
- `style_key` 必须存在于 `prompts/styles.py` 注册表。
- `aspect_ratio` 和 `resolution` 必须来自后端能力接口；前端不得自行维护另一份创建选项。
- 旧项目读取时优先使用规范字段；字段为空时才保留现有描述字符串兼容解析。新项目禁止再把配置编码到描述字符串或 `sessionStorage`。

### 4.2 RemakeUpload 暂存表

| 字段 | 类型 | 默认/约束 |
| --- | --- | --- |
| `id` | UUID | 主键，同时作为不透明 `upload_token` |
| `storage_provider` | `VARCHAR(16)` | `local` 或 `oss` |
| `object_key` | `VARCHAR(500)` | 非空，只保存受控 key/相对路径，不保存临时签名 URL |
| `original_filename` | `VARCHAR(255)` | 非空，必须去除客户端路径部分 |
| `mime_type` | `VARCHAR(120)` | 可空，仅作展示，不作为格式判定依据 |
| `size_bytes` | BIGINT | 大于 0，最大 524288000 |
| `duration_seconds` | FLOAT | `0 < duration <= 1200` |
| `width` / `height` | INT | 均大于 0 |
| `container_format` | `VARCHAR(32)` | `ffprobe` 规范化结果 |
| `checksum` | `VARCHAR(64)` | SHA-256，非空 |
| `status` | `VARCHAR(16)` | `uploading/validating/ready/committed/failed/expired` |
| `error_code` / `error_message` | `VARCHAR(64)` / TEXT | 可空 |
| `team_id` / `created_by` | INT | 可空但必须与鉴权上下文一致 |
| `expires_at` | DATETIME | 非空；默认创建后 24 小时 |
| `committed_at` | DATETIME | 可空 |

安全规则：

- 暂存 token 只能被其创建者和所属团队使用。
- `ready` token 只能成功提交一次；重复幂等请求返回原项目，其他请求返回 `REMAKE_UPLOAD_ALREADY_COMMITTED`。
- 清理器只删除 `uploading/validating/ready/failed` 且已过期的暂存对象，不删除已绑定来源。
- OSS 直传终局和本地流式上传必须进入同一套媒体探测与状态转换。

### 4.3 RemakeSource 来源表

| 字段 | 类型 | 默认/约束 |
| --- | --- | --- |
| `id` | INT | 主键 |
| `novel` | FK → Novel | `CASCADE`，索引 |
| `chapter` | OneToOne → Chapter | `CASCADE`，唯一 |
| `episode_number` | INT | 大于 0；`(novel_id, episode_number)` 唯一 |
| `source_kind` | `VARCHAR(16)` | `upload` 或 `history` |
| `storage_provider` | `VARCHAR(16)` | `local` 或 `oss` |
| `object_key` | `VARCHAR(500)` | 非空、提交后不可编辑 |
| `original_filename` | `VARCHAR(255)` | 非空 |
| `mime_type` | `VARCHAR(120)` | 可空 |
| `size_bytes` | BIGINT | 大于 0，最大 524288000 |
| `duration_seconds` | FLOAT | `0 < duration <= 1200` |
| `width` / `height` | INT | 均大于 0 |
| `container_format` | `VARCHAR(32)` | 非空 |
| `checksum` | `VARCHAR(64)` | SHA-256，非空 |
| `source_novel_id` / `source_chapter_id` | INT | 历史来源必填；保存审计 ID，不设外键，避免原记录删除破坏快照 |
| `source_video_manifest` | JSON | 历史来源必填；上传来源为空对象 |
| `media_status` | `VARCHAR(16)` | `ready/processing/completed/failed` |
| `analysis_task` | FK → AiTask | 可空，`SET_NULL`；始终指向当前一次任务 |
| `team_id` / `created_by` | INT | 与目标项目归属一致 |

`source_video_manifest` 最低结构：

```json
{
  "snapshot_created_at": "2026-08-28T10:00:00+08:00",
  "source_novel_id": 12,
  "source_chapter_id": 34,
  "segments": [
    {"scene_id": 101, "video_id": 501, "position": 1, "checksum": "..."}
  ],
  "snapshot_checksum": "..."
}
```

历史项目删除或重新生成后，`object_key` 指向的快照仍需可读；清单中的 ID 只用于审计，不再参与运行时取源。

### 4.4 AiTask 增量字段与任务类型

| 字段 | 类型 | 默认/约束 |
| --- | --- | --- |
| `stage` | `VARCHAR(32)` | 可空；非拆解任务不受影响 |
| `progress` | INT | 默认 0，范围 0–100 |

新增 `AiTaskTypeEnum.remake_decomposition = 6`。一个 `RemakeSource` 同一时刻最多有一个 `pending/queued/running` 拆解任务，服务层必须用事务和条件检查保证该约束。

重试关系不增加专用字段，写入新任务 `request_params.retry_of_task_id` 和 `request_params.attempt`；`RemakeSource.analysis_task_id` 原子切换到新任务。旧任务保留用于审计。

### 4.5 数据库兼容策略

- 新安装仍由 `Tortoise.generate_schemas(safe=True)` 创建完整表。
- 旧 SQLite 由幂等兼容服务只增列、建缺失表并回填 `workflow_kind=script`，不得删列、删表或覆盖已有值。
- PostgreSQL 使用 `ADD COLUMN IF NOT EXISTS`/`CREATE TABLE IF NOT EXISTS` 等等价增量语句。
- 连续执行兼容逻辑两次，第二次不得写重复数据或报错。
- `RemakeUpload` 和 `RemakeSource` 是新表，无历史回填。

> 本节涉及数据结构变更，P1 实施前标记为：**需人工审核**。

## 5. 媒体与集数规则

### 5.1 媒体权威校验

- 最大字节数：`524288000`（500 × 1024 × 1024）。恰好等于上限允许，超过 1 字节拒绝。
- 最大时长：`1200.000` 秒。恰好等于上限允许，超过即拒绝。
- 文件扩展名不区分大小写，仅允许 `.mp4`、`.mov`。
- `ffprobe` 必须确认存在视频流，并成功获取时长、宽高和容器。
- 扩展名、浏览器 MIME 与真实容器不一致时拒绝；MIME 为空但真实容器合法时允许。
- 不限制合法视频编码；分析代理统一为 H.264/AAC 时，原始来源仍保留不变。
- 校验顺序为：文件名与扩展名 → 流式字节上限 → `ffprobe` → 时长/视频流 → SHA-256。

### 5.2 集数解析优先级

去除扩展名后，按以下不区分大小写的模式解析；每个文件必须且只能得到一个集数：

1. `第\s*(\d+)\s*[集话]`
2. `\bEP\s*0*(\d+)\b`
3. `\bE\s*0*(\d+)\b`
4. `(?<!\d)0*(\d+)\s*集(?!\d)`

规则：

- 集数必须在 `1..99999`。
- 同一文件匹配到多个不同集数时返回歧义错误。
- 同一批次集数重复为硬错误。
- 集数不连续为警告，用户确认后可继续。
- 非 MP4/MOV 文件不上传，在列表中显示为“已忽略”。
- 单视频不解析文件名，服务端固定 `episode_number=1`。
- 历史模式由原章节 `number` 得出集数，重复时阻止创建。

## 6. API 契约

### 6.1 统一响应和错误结构

沿用现有 `ResponseSchema`：HTTP 协议响应继续兼容当前异常处理器；业务调用以响应体 `code == 0` 判断成功。

成功：

```json
{"code": 0, "data": {}, "message": "操作成功"}
```

业务失败：

```json
{
  "code": 422,
  "data": {
    "error_code": "REMAKE_MEDIA_DURATION_EXCEEDED",
    "context": {"filename": "第1集.mp4", "limit_seconds": 1200},
    "retryable": false
  },
  "message": "视频时长不能超过20分钟"
}
```

`message` 面向用户且可调整；前端逻辑只能依赖稳定的 `data.error_code`。无法归类的现有异常仍按当前通用响应处理。

### 6.2 GET `/api/remake/capabilities`

返回页面唯一能力来源：

```json
{
  "code": 0,
  "data": {
    "source_modes": ["single_upload", "folder_upload", "history"],
    "media": {
      "extensions": ["mp4", "mov"],
      "max_bytes": 524288000,
      "max_duration_seconds": 1200,
      "upload_expires_seconds": 86400
    },
    "episode_patterns": ["第12集", "第12话", "EP12", "E12", "12集"],
    "aspect_ratios": ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9"],
    "resolutions": ["480p", "720p", "1080p", "4k", "768P", "2K"],
    "default_aspect_ratio": "9:16",
    "default_resolution": "720p",
    "styles": [{"key": "realistic-general", "label": "写实通用"}],
    "upload": {"direct": false, "provider": "local"}
  },
  "message": "操作成功"
}
```

- 比例来自后端视频能力注册表并排除 `adaptive`，因为项目必须有确定画幅。
- 清晰度是后端已注册视频能力的有序去重并集；具体生成时仍由所选视频模型再次校验。
- 风格直接复用 `prompts/styles.py`。
- OSS 开启时只改变 `upload` 内容，不改变媒体规则。

### 6.3 上传接口

#### GET `/api/remake/uploads/policy`

查询参数：`filename`、`content_type`、`size_bytes`。仅 OSS 模式返回直传表单；签名最大值固定为 500MiB，并将 `purpose=remake_source` 写入受控 key。该接口只做轻量预检，不代表媒体已通过终局校验。

#### POST `/api/remake/uploads`

本地模式使用单个 `multipart/form-data` 字段 `file`，服务端分块写入，超过上限立即中止并清理。OSS 模式返回 `REMAKE_UPLOAD_DIRECT_REQUIRED`，避免 500MiB 经应用进程中转。

成功后已经完成媒体终局校验，返回：

```json
{
  "upload_token": "d122f5aa-6dc9-4d64-8942-74b20f707126",
  "original_filename": "第1集.mp4",
  "size_bytes": 12345678,
  "duration_seconds": 63.42,
  "width": 1920,
  "height": 1080,
  "status": "ready",
  "expires_at": "2026-08-29T10:00:00+08:00"
}
```

#### POST `/api/remake/uploads/finalize`

OSS 直传后提交：

```json
{"object_key": "...", "original_filename": "第1集.mp4"}
```

服务端校验 key 用途和所有权，经受控读取运行同一媒体校验器，创建 `RemakeUpload` 并返回与本地上传相同的结果。

#### DELETE `/api/remake/uploads/{upload_token}`

仅允许释放当前用户未提交的暂存对象。已提交 token 返回 `REMAKE_UPLOAD_ALREADY_COMMITTED`。删除成功必须同时删除暂存对象和数据库记录；该操作不可恢复。

### 6.4 历史项目接口

#### GET `/api/remake/history/projects`

支持 `keyword/page/page_size`，只返回当前权限范围且至少有一个可用章节的非当前重制目标项目：

```json
{
  "items": [
    {"id": 12, "name": "旧项目", "cover": null, "available_episode_count": 8}
  ],
  "pagination": {"total": 1, "page": 1, "page_size": 20, "pages": 1}
}
```

#### GET `/api/remake/history/projects/{novel_id}/episodes`

```json
[
  {
    "chapter_id": 34,
    "episode_number": 1,
    "name": "第1集",
    "duration_seconds": 83.5,
    "size_bytes": 34567890,
    "scene_count": 12,
    "available": true,
    "unavailable_reason": null
  }
]
```

不可用章节也返回，供界面解释原因；原因包括无分镜、存在未完成分镜、当前版本缺失、严格合成失败、超大小和超时长。

### 6.5 POST `/api/remake/projects`

三种来源使用同一请求：

```json
{
  "name": "都市短剧重制",
  "source_mode": "folder_upload",
  "aspect_ratio": "9:16",
  "resolution": "1080p",
  "style_key": "realistic-cinematic",
  "custom_style_prompt": null,
  "idempotency_key": "55f5842a-7f1a-49d4-b960-b5ea3761343b",
  "sources": [
    {"episode_number": 1, "upload_token": "...", "source_chapter_id": null},
    {"episode_number": 2, "upload_token": "...", "source_chapter_id": null}
  ]
}
```

模式约束：

- `single_upload`：恰好一个 `upload_token`，集数必须为 1。
- `folder_upload`：至少一个 `upload_token`，每个集数唯一；服务端按暂存记录的原文件名重新解析并核对客户端集数。
- `history`：每项只传 `source_chapter_id`；服务端重新检查权限、可用性、集数并创建快照。
- `style_key` 与 `custom_style_prompt` 二选一。
- `idempotency_key` 是 UUID 字符串。相同鉴权主体、相同 key 的后续调用直接返回第一次结果；payload 不同则返回 `REMAKE_IDEMPOTENCY_CONFLICT`。

创建事务边界：

1. 解析并锁定幂等键。
2. 再次校验所有来源及权限。
3. 历史来源先完成严格合成和不可变媒体快照；任一失败不创建项目。
4. 在同一数据库事务创建 `Novel`、所有 `Chapter`、`RemakeSource` 和 `AiTask`，并把暂存 token 标记为 `committed`。
5. 事务提交后投递每集任务；投递失败将任务标记 `failed`，项目和来源保留并允许重试。

返回 HTTP 响应体：

```json
{
  "code": 0,
  "data": {
    "novel_id": 88,
    "workflow_kind": "remake",
    "entry_path": "/create/short-drama/manual/88",
    "sources": [
      {"source_id": 201, "chapter_id": 301, "episode_number": 1, "task_id": "...", "status": "queued"}
    ]
  },
  "message": "重制项目创建成功"
}
```

### 6.6 项目与任务查询

- `GET /api/remake/projects/{novel_id}`：返回项目配置、来源汇总和聚合状态。
- `GET /api/remake/projects/{novel_id}/sources`：按集数返回来源和当前任务。
- `GET /api/remake/sources/{source_id}`：返回单集来源、任务详情和只读媒体播放地址。
- `POST /api/remake/sources/{source_id}/analysis/retry`：仅 `failed` 状态可重试；若已有活跃任务，幂等返回该任务。

查询接口必须复用现有项目权限规则。播放地址由服务端按需解析或签名，数据库不保存可过期 URL。

## 7. 状态机

### 7.1 暂存媒体

```text
uploading → validating → ready → committed
    │           │          │
    └───────────┴──────────┴→ failed
                           └→ expired（仅未提交且到期）
```

- `committed` 是终态，不允许释放或重新绑定。
- `failed/expired` 不可创建项目，重新上传会得到新 token。

### 7.2 单集拆解

`AiTask.status` 表示任务生命周期，`stage` 表示运行步骤：

```text
pending → queued → running → completed
                    ├──────→ failed
                    └──────→ cancelled

queued
  → preparing          0–10
  → detecting_scenes  10–30
  → extracting_assets 30–60
  → generating_storyboards 60–90
  → persisting        90–99
  → completed            100
```

- 进度只能单调增加；失败时保留最后阶段和进度。
- `completed` 时必须存在该章节的已提交资产/分镜结果。
- 持久化在事务中执行，失败不得留下半套结果。
- 重试先删除或替换该来源上一次未完成的拆解草稿范围，不触碰人工创建或其他来源已完成的数据；具体来源标识保存在资产/分镜 metadata 中。
- 自动分镜写入 `Scene.metadata.remake_source_id` 和 `analysis_task_id`；自动资产在 `Asset.metadata.remake_source_ids` 中维护来源集合。资产按项目、类型和规范名复用，重试只撤销本来源的关联，不删除仍被其他来源或人工分镜引用的资产。
- 后端启动时，超过任务超时阈值的 `running` 任务标为失败并给出可重试错误，不静默永久挂起。

### 7.3 项目聚合状态

- `queued`：尚无来源运行且至少一集待处理。
- `processing`：至少一集处于活跃任务。
- `completed`：全部来源拆解完成。
- `partial_failed`：至少一集失败且至少一集完成或仍活跃。
- `failed`：全部来源失败。

聚合状态由来源和任务实时计算，不新增可漂移的项目状态字段。

## 8. 稳定错误码

| 错误码 | code | 可重试 | 触发场景 |
| --- | ---: | --- | --- |
| `REMAKE_MEDIA_EXTENSION_UNSUPPORTED` | 422 | 否 | 非 MP4/MOV |
| `REMAKE_MEDIA_SIZE_EXCEEDED` | 413 | 否 | 超过 500MiB |
| `REMAKE_MEDIA_INVALID_CONTAINER` | 422 | 否 | 容器伪装、损坏或不可探测 |
| `REMAKE_MEDIA_VIDEO_STREAM_MISSING` | 422 | 否 | 不含视频流 |
| `REMAKE_MEDIA_DURATION_INVALID` | 422 | 否 | 时长缺失或不大于 0 |
| `REMAKE_MEDIA_DURATION_EXCEEDED` | 422 | 否 | 超过 1200 秒 |
| `REMAKE_EPISODE_MISSING` | 422 | 否 | 文件夹文件名无集数 |
| `REMAKE_EPISODE_AMBIGUOUS` | 422 | 否 | 一个文件名解析出多个不同集数 |
| `REMAKE_EPISODE_DUPLICATED` | 409 | 否 | 批次集数重复 |
| `REMAKE_UPLOAD_NOT_FOUND` | 404 | 否 | 暂存 token 不存在或无权访问 |
| `REMAKE_UPLOAD_NOT_READY` | 409 | 是 | 暂存仍在上传/校验 |
| `REMAKE_UPLOAD_EXPIRED` | 410 | 否 | 暂存已过期 |
| `REMAKE_UPLOAD_ALREADY_COMMITTED` | 409 | 否 | 暂存已被其他请求绑定 |
| `REMAKE_UPLOAD_DIRECT_REQUIRED` | 409 | 是 | OSS 模式要求浏览器直传 |
| `REMAKE_SOURCE_MODE_MISMATCH` | 422 | 否 | 来源字段与模式不一致 |
| `REMAKE_PROJECT_CONFIG_INVALID` | 422 | 否 | 比例、清晰度或风格无效 |
| `REMAKE_IDEMPOTENCY_CONFLICT` | 409 | 否 | 相同 key 的 payload 不同 |
| `REMAKE_HISTORY_PROJECT_FORBIDDEN` | 403 | 否 | 无历史项目权限 |
| `REMAKE_HISTORY_EPISODE_UNAVAILABLE` | 422 | 否 | 历史章节不满足严格合成条件 |
| `REMAKE_HISTORY_SNAPSHOT_FAILED` | 500 | 是 | 严格合成或快照写入失败 |
| `REMAKE_ACTIVE_ANALYSIS_EXISTS` | 409 | 是 | 已有活跃拆解任务 |
| `REMAKE_ANALYSIS_NOT_RETRYABLE` | 409 | 否 | 非失败任务请求重试 |
| `REMAKE_ANALYSIS_MODEL_UNAVAILABLE` | 503 | 是 | 未配置可用拆解模型 |
| `REMAKE_ANALYSIS_FAILED` | 500 | 是 | 拆解流程失败 |

鉴权失败时不得通过“404/403 差异”泄露其他团队的 token、项目或来源详情；资源级查询沿用现有权限服务的隐藏策略。

## 9. 模型配置与计费边界

- 新增模型任务能力 `remake_decomposition=6`，不写供应商或模型名称特例。
- 拆解任务通过 `AiModelConfigController.get_active(6, team_id=...)` 解析唯一 LLM 配置；团队配置优先和官方回退沿用现有规则。
- 默认 LLM 种子配置仅在现有幂等扫描中补充任务能力 6，不覆盖管理员已有 key、启用状态、定价或模型选择。
- 一个来源对应一个 `AiTask`；该任务内的资产与分镜分析都使用同一个已解析配置，避免中途切换产生不可复现结果。
- 处理器聚合该任务全部文本调用 token，并通过现有 `BillingRecorder.record_text` 以 `task_type=6` 写一条计费流水；失败也记录已经产生的 token。
- 本地 `ffprobe`、转码、场景检测、数据库持久化不产生模型计费记录。
- 创建项目和上传不调用外部模型；只有任务真正开始拆解时产生外部调用。
- P3 上线前需要在 UI 明示将开始模型分析；余额不足、模型未配置必须在外部调用前失败。

> 本节会增加外部模型调用和余额消耗路径，P3 实施前标记为：**需人工审核**。

## 10. 页面状态与交互

### 10.1 创建页状态

```text
loading_capabilities
  → selecting_source
  → validating_selection
  → uploading
  → ready_to_create
  → creating
  → created（跳转项目）
  └→ error（保留已选内容，可局部重试）
```

全局规则：

- 能力接口失败时禁用上传和创建，并提供重试。
- 切换来源模式前若已有暂存，提示会释放未提交暂存；用户确认后调用删除接口。
- 上传完成但项目未创建时离开页面，弹出提示；服务端仍由过期清理兜底。
- `creating` 时按钮禁用，但重复网络请求仍必须由后端幂等保护。

### 10.2 单视频

- 拖拽或选择一个文件。
- 前端快速校验扩展名和声明大小，服务端校验是最终结论。
- 显示文件名、大小、时长、画面尺寸、上传进度和失败原因。
- 单视频默认第 1 集，不要求文件名有集数。

### 10.3 文件夹

表格列：文件名、解析集数、大小、状态、进度、问题、操作。

- 选择后先本地解析全部文件，再开始上传。
- 无集数、歧义、重复集数阻止上传和创建。
- 断集显示黄色警告和缺失集数，用户可确认继续。
- 非视频文件显示“已忽略”，不计入来源数量。
- 单文件失败只重试该文件；合法文件无需重传。

### 10.4 历史项目

- 左侧项目搜索/分页，右侧章节列表。
- 不可用章节禁用并显示原因。
- 支持同一个历史项目内选择多集；第一版不跨历史项目混选。
- 提交前明确提示将制作不可变快照，原项目不会被修改。

### 10.5 项目配置

- 比例和清晰度为必选，默认值来自能力接口。
- 风格选择“系统风格”或“自定义风格”二选一。
- 自定义风格去除首尾空白后长度为 1–2000 字符。
- 在创建按钮附近汇总：来源模式、集数、总大小、总时长、比例、清晰度和风格。

### 10.6 无限画布

- `source_video`：只读播放、集数、来源类型、原文件名、时长、尺寸。
- `ai_decomposition`：阶段中文名、进度条、最后错误、失败重试。
- 拆解中同时显示来源和任务节点；完成后保留来源节点，移除任务临时节点，展示资产和分镜。
- 刷新页面后完全从后端重建状态，不依赖内存轮询结果。
- 多集切换只展示当前章节对应来源和拆解状态，项目资产仍按现有共享规则加载。

## 11. 人工验收样例

### P0 文档验收

1. 三种来源是否确实使用同一创建接口和来源模型。
2. 是否接受“创建后自动拆解，但不自动生成设定图/视频”的费用边界。
3. 是否接受项目比例排除 `adaptive`，清晰度在实际选模型时再次校验。
4. 是否接受历史来源创建不可变快照而非引用可覆盖成片。
5. 是否接受文件夹断集只警告，重复/无集数/歧义为硬错误。
6. 是否批准 P1 的增量数据库结构方案。
7. 是否批准 P3 新增 `PySceneDetect` 依赖及锁文件变化。
8. 是否批准 P3 的外部模型调用和计费路径。

### 后续端到端验收数据集

| 样例 | 预期 |
| --- | --- |
| `demo.mp4`，500MiB，1200 秒，单视频 | 允许 |
| `demo.mp4`，500MiB + 1 字节 | 拒绝大小超限 |
| `demo.mov`，1200.001 秒 | 拒绝时长超限 |
| 改名为 `.mp4` 的文本文件 | 拒绝容器无效 |
| 只有音频流的 MOV | 拒绝无视频流 |
| `第1集.mp4、EP02.mov、3集.MP4` | 创建 1、2、3 三集 |
| `第1集.mp4、第1话.mov` | 阻止，重复集数 |
| `第1集.mp4、第3集.mp4` | 警告缺第2集，确认后允许 |
| `花絮.mp4`（文件夹模式） | 阻止，无集数 |
| 无权限历史项目 ID | 不泄露详情，拒绝 |
| 缺一个分镜当前视频的历史章节 | 显示不可用，不可提交 |
| 同一幂等 key 连点两次 | 只产生一个项目 |
| 某一集模型失败 | 其他集继续；失败集可单独重试 |

## 12. 分阶段 TDD 执行顺序

每项实现必须遵循“先写失败测试并确认失败原因 → 最小实现 → 回归和重构”。不得先实现后补形式测试。

### P1 数据与兼容

1. 后端模型/schema 测试先断言新字段、默认值、唯一约束。
2. 兼容测试构造旧 SQLite schema，首次启动补齐字段和表，二次启动幂等。
3. 回归测试断言旧项目仍按 `script` 工作，既有种子数据不重复。
4. 再实现模型、schema 和兼容服务。

建议测试文件：

- `test/test_models/test_remake_models.py`
- `test/test_services/test_remake_schema_compat.py`
- `test/test_api/test_novel_api.py` 增量用例

### P2 单视频

1. 媒体校验器单元测试覆盖全部边界和 `ffprobe` 异常。
2. 暂存服务测试覆盖流式上限、所有权、过期、提交和清理。
3. 创建服务测试覆盖事务回滚和幂等冲突。
4. API 测试覆盖本地/OSS 分支和稳定错误码。
5. 前端组件测试覆盖页面状态、上传重试和重复点击。
6. 再实现服务、API 和页面。

建议测试文件：

- `test/test_services/test_remake_media.py`
- `test/test_services/test_remake_uploads.py`
- `test/test_services/test_remake_project_creation.py`
- `test/test_api/test_remake_api.py`
- `web/src/pages/RemakeWorkshopPage.spec.ts`

### P3 拆解

1. Prompt 渲染与 JSON 契约测试。
2. 场景检测器测试使用小型合成测试视频或 mock，不提交媒体文件。
3. 资产归一化、镜头排序、引用解析的纯服务测试。
4. 任务测试覆盖阶段单调、超时、部分 token 计费和重试去重。
5. 事务测试先制造持久化中途失败，断言无半套数据。
6. 再实现 Prompt、服务对象、处理器和计费适配。

建议测试文件：

- `test/test_prompts/test_remake_decomposition_prompts.py`
- `test/test_services/test_remake_scene_detector.py`
- `test/test_services/test_remake_decomposition.py`
- `test/test_services/test_remake_persistence.py`
- `test/test_services/test_remake_task_handler.py`

### P4 无限画布

1. Store 测试先断言来源/任务数据到节点和边的映射。
2. 节点组件测试覆盖播放、状态、错误、重试和完成切换。
3. 画布回归测试覆盖现有节点、视口和撤销重做不变。
4. 生成参数测试断言项目默认值进入资产和镜头调用。
5. 合成节点测试先断言严格完整性，再接真实执行。

### P5 历史来源

1. 权限与可用章节查询测试。
2. 严格合成测试覆盖缺镜头、失败视频、顺序和边界。
3. 快照测试断言原视频变化/删除后快照不变。
4. 幂等创建和失败清理测试。
5. 再实现 API、服务和选择器。

### P6 文件夹多集

1. 集数解析参数化测试覆盖中英文、大小写、前导零、歧义。
2. 批次校验测试覆盖重复、断集、忽略文件和排序。
3. 多集创建事务和单集任务隔离测试。
4. 前端表格、并发上传、单文件重试测试。
5. 再开放文件夹模式。

### P7 发布加固

1. 先将真实边界、鉴权、刷新、重启、并发和故障场景写成回归测试或可重复脚本。
2. 修复每个失败的最小根因。
3. 运行后端全部 pytest、前端全部 Vitest、类型检查、生产构建和 `git diff --check`。

## 13. P0 验收门禁

P0 通过必须同时满足：

- 用户确认本规格第 2–10 节的产品和技术边界。
- 用户明确批准或拒绝 P1 增量数据库方案。
- 用户明确批准或拒绝 P3 增加 `PySceneDetect` 依赖并更新 `pyproject.toml`、`uv.lock`。
- 用户明确批准或拒绝 P3 外部模型调用和计费边界。
- 未批准的事项不得通过隐含假设实施。

P0 验收后进入 P1，并在 P1 完成后再次暂停验收。
