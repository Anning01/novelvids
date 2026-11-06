# 助手事件流去轮询与历史接口 N+1 优化

临时文件：用于在"新建会话"里粘贴成 brief。粘贴后可以删除。

## 背景

仓库是 novel-vids（AI 小说转短剧平台，后端 FastAPI + Tortoise ORM + Pydantic AI，前端 Vue 3）。创作助手是 `services/creation_agent/` 下的一套 Pydantic AI 智能体：对话运行由 `services/creation_agent/handler.py` 执行，通过 AG-UI 协议向前端推送事件，前端在 `web/src/features/creation-agent/store.ts` 与 `api.ts` 里订阅。

一次架构评审确认了三处相关的轮询式性能隐患，都已定位到行号：

1. `services/creation_agent/handler.py` 的 `flush()`（约 162-168 行）与 0.2 秒节流调用点（约 229-230 行）每隔不超过 0.2 秒把整个 `AgentMessage.events` JSON 数组整体重写一次，数组没有上限，长运行呈平方级写入。
2. `api/creation_agent.py` 的事件流端点（约 100-136 行）每 0.15 秒为每个订阅客户端重读整行 AgentMessage 并查一次 AiTask。
3. `controllers/creation_agent.py` 的 `messages()`（约 86-102 行）对每条消息各调 4 次查询，其中 `services/creation_agent/receipts.py` 的 `usage_summary`（约 51-72 行）每次加载整个会话的 assistant 消息。

## 目标

把事件持久化与订阅从"固定节奏整表轮询"改为有界、按需唤醒，并消掉历史接口的 N+1。完成后在最终说明里列出事件存储方案的取舍与对旧数据的兼容方式。

1. 不再每次整体重写 `events` 数组。可选方案是追加写（新表或分段存储），或给 `events` 设上限并把超出部分归档到 `AgentContextCheckpoint` 一类可回查的记录。选择时以保留 `after` 游标回放为前提。
2. 事件流端点用进程内 `asyncio.Condition` 或等价的通知机制替代 0.15 秒固定轮询，只在有新事件或任务状态变化时读库；必须保留断线重连按 `after` 续传，以及运行结束时的 RUN_FINISHED/RUN_ERROR 收口判断（当前逻辑在 `task.status` 非活跃且最后一条事件不是终止事件时补发 RunErrorEvent）。
3. 历史接口改为批量查询，`usage_summary` 不再每次加载整个会话。

## 必须保持的契约

- AG-UI 事件回放语义：`after` 游标、RUN_FINISHED/RUN_ERROR 终止判断、`_EVENT_ADAPTER` 校验。
- `AgentMessage.events` 对旧记录仍可读，不删除历史数据。
- 前端 `store.ts` 与 `api.ts` 不做改动即可正常跟随运行（`onToolCallResultEvent` 会调 snapshot，`follow` 依赖 RUN_STARTED 与消息事件重建状态）。
- `services/creation_agent/results.py` 的 `query_results`/`message_changes` 与 `controllers/creation_agent.py` 的 `event_count` 仍要能工作。

## 仓库规范

遵循 AGENTS.md：api → controllers → models/services 分层；用 `Tortoise.generate_schemas(safe=True)` 安全建表，新增表或字段必须补数据库初始化、旧数据兼容与重复启动测试；修改业务行为必须加回归测试；不要删除历史迁移或兼容逻辑；提交前跑相关 pytest 并执行 `git diff --check`；提交信息用 `type(scope): description`。

## 测试

```bash
AUTH_ENABLED=false uv run pytest test/test_services/test_creation_agent_handler.py test/test_services/test_creation_agent_sessions.py -q
AUTH_ENABLED=false uv run pytest
```

开发机 shell 里导出了 `.env` 的 `AUTH_ENABLED=true`，会让约 200 个鉴权相关测试失败，所以必须带 `AUTH_ENABLED=false` 运行。

为三处改动各补回归测试，至少覆盖长运行的事件数量上限或追加行为、断线后按 after 续传、以及历史接口的查询次数。用 TDD：先写会失败的测试，确认失败原因后再改实现。

## 完成标准

相关 pytest 与全量 pytest 全绿、`git diff --check` 干净、前端无需改动即可跟随运行、事件存储方案与兼容方式写进最终说明。在自己的分支上提交，不要 push。
