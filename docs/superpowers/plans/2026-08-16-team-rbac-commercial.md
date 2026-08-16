# 登录权限与团队功能（单仓开关方案）— 总体计划

> **状态: 已实施完成（2026-08-16，P0–P8 全部落地）。** 部署与运维文档见 `docs/team-auth-deployment.md`；两态回归：vanilla 全量（关闭开关）+ `AUTH_ENABLED=true uv run pytest test/test_auth`（83 个测试）+ 前端 321 个测试。
>
> 已确认关键决策（2026-08-16）：
> - **D1 单仓开关**：只维护一套代码，`AUTH_ENABLED` 一个开关控制。关闭时与现状 100% 一致（docker 部署即用、无登录）；开启后必须登录，**团队功能默认随之开启**（无需第二个开关）。
> - **D2 登录方式**：先做**账号密码登录**上线；微信公众号扫码关注登录作为第二种登录方式，服务号资质办好后通过 Provider 接口接入（流程设计已就绪）。
> - **D3 余额策略**：提交预检 + 完成扣减 + 允许透支标红，欠费团队禁新任务。
> - **D4 Key 可见性**：团队管理员可见本团队 Key；官方配置 Key 对超管以外任何角色永不外泄。
>
> **目标:** 在现有仓库内实现开关式登录权限与团队能力：关闭开关 = 今天的开源体验；打开开关 = 登录 + 四级角色 + 团队数据隔离 + 官方模型配置 + 团队余额。

---

## 1. 单仓开关策略（核心决策）

### 1.1 一个开关，两种形态

| 维度 | `AUTH_ENABLED=false`（默认） | `AUTH_ENABLED=true`（线上版） |
|---|---|---|
| 登录 | 无，直接进入 | 强制登录，未登录跳转 `/login` |
| 团队功能 | 全部隐藏 | 默认开启（角色/成员管理/团队管理/官方配置/余额） |
| 数据模型 | 不建 auth 表、不注册 auth 路由（条件注册，零痕迹） | 完整建表与注册 |
| 权限依赖 | 全部 no-op | 严格鉴权 + 团队隔离 |
| Docker | `docker compose up -d` 即用，与今天完全一样 | 设置 `AUTH_ENABLED=true` + 超管引导 |
| 测试 | 现有测试套件原样通过（vanilla 基线） | RBAC 矩阵 + 商业测试 |

- **默认关闭**：开源用户零门槛，保持 README「docker 部署即用」的承诺。
- **开启即团队**：登录与团队功能绑在一个开关上（默认 `TEAM_ENABLED=AUTH_ENABLED`），不引入第二个开关；未来确需拆开时再增加，避免过度设计。
- **维护收益**：一份代码，bug 修一次、两态同时生效，不存在双仓同步与合并冲突。

### 1.2 公开可见性影响（需知晓）

仓库是公开的（CC BY-NC 4.0），登录/团队/余额代码会随之公开。商业化的价值点从「代码闭源」转为「线上运营与部署服务」；代码闭源售卖不再成立。如需代码层面的独占，此方案不适用（需回到双仓方案）。

---

## 2. 开关行为契约（两态都必须有测试钉死）

- **关闭态**：所有现有 API 行为、响应结构、数据库表集合、前端页面/导航与今天逐字节一致；auth 相关表不创建（模型条件注册）。
- **开启态**：见下文的权限矩阵、团队隔离、官方配置、余额规则。

---

## 3. 角色与权限矩阵

| 能力 | 超级管理员（平台级） | 团队管理员 | 创作者 | 查看者 |
|---|:---:|:---:|:---:|:---:|
| 项目管理（小说 CRUD/章节拆分/分析） | ✓ 全部团队 | ✓ 本团队 | ✓ 本团队 | 只读 |
| 资产/分镜/视频生成与编辑 | ✓ | ✓ | ✓ | 只读 |
| 设置页 / 模型配置 | ✓（官方配置） | ✓（团队配置，或切换"使用官方配置"） | ✗ | ✗ |
| 成本看板 | ✓ 全部团队 | ✓ 本团队全部成员 | ✓ **仅本人** | ✗ |
| 成员管理页 | ✓ 全部团队 | ✓ 本团队 | ✗ | ✗ |
| 团队管理页（创建团队/设余额/停用） | ✓ | ✗ | ✗ | ✗ |
| 创建/修改/删除任何数据 | ✓ | ✓ | ✓（团队内） | ✗ |

- 超管不隶属任何团队（`is_super_admin=true`），可跨团队访问全部数据。
- 查看者：所有 GET 允许（团队范围内），所有 POST/PATCH/DELETE 一律 403。
- 创作者：设置接口 403；计费接口按 `user_id` 强制过滤本人。

---

## 4. 数据模型设计

### 4.1 新增表（仅在 `AUTH_ENABLED=true` 时注册）

| 模型 | 关键字段 |
|---|---|
| `User` | `id, username, password_hash, unionid?, openid?, nickname, avatar_url, is_super_admin, status` |
| `Team` | `id, name, balance(Decimal 18,6), model_config_source('official'/'custom'), status` |
| `TeamMember` | `id, team_id, user_id, role(admin/creator/viewer), unique(team_id,user_id)` |
| `UserSession` | `id, token_hash, user_id, expires_at, last_seen_at` |
| `BalanceTransaction` | `id, team_id, change_amount, balance_after, type(topup/consume/adjust), usage_record_id?, operator_user_id, note` |

### 4.2 存量表改造（加列，走 `services/schema_compat.py` 现有模式）

| 表 | 变更 | 说明 |
|---|---|---|
| `novels` | `+team_id`（索引）、`+created_by` | 团队数据隔离的根 |
| `model_usage_records` | `+team_id`、`+user_id` | 成本按团队/成员过滤 |
| `ai_model_configs` | `+scope('official'/'team')`、`+team_id`（可空） | `team_id=NULL + scope=official` = 官方配置；`scope=team + team_id=X` = 团队自有配置 |
| 媒体库相关表 | `+team_id` | 全局媒体库按团队隔离 |
| 其余表（chapters/assets/scenes/videos/ai_tasks） | 不直接加列 | 一律经 `novel_id` 关联到团队 |

### 4.3 存量数据回填（首次开启登录时）

- 建默认团队，把全部存量 `novels` 挂入；`model_usage_records` 按 `novel_id` 回填 `team_id`。
- 首个超管：环境变量 `SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD` 引导（首次启动自动创建），或一次性 CLI `scripts/promote_super_admin.py`。
- 回填写成幂等迁移，进 `services/schema_compat.py` 迁移链，带测试。

---

## 5. 认证与会话

### 5.1 第一期：账号密码登录（立即可上线）

```
POST /api/auth/login { username, password }   → 校验 → 建 UserSession → 返回 token + 用户信息
GET  /api/auth/me                            → 用户 + 成员信息 + 权限位
POST /api/auth/logout                        → 吊销会话
POST /api/auth/change-password               → 修改密码
```

- 密码：stdlib `hashlib.pbkdf2_hmac` + 随机盐（不新增依赖）；首次登录引导修改初始密码。
- 会话：不透明 token 存库（可吊销），前端 `Authorization: Bearer`，401 统一跳登录。
- 成员账号由团队管理员/超管创建并发放初始密码。

### 5.2 第二期：微信公众号扫码关注登录（资质就绪后热接入）

```
前端 /login（微信标签页）
  └─ POST /api/auth/wechat/qrcode → 生成 QR_STR_SCENE 临时二维码（300s）→ 前端展示
  └─ 轮询 GET /api/auth/wechat/qrcode/{scene}/status（waiting/scanned/success{token}/expired）
用户扫码 → 确认关注公众号
  └─ 微信服务器 POST XML 事件到 /api/wechat/mp/events（公网 HTTPS，签名校验 + echostr 验证）
       subscribe + EventKey=qrscene_<scene>   ← 新关注登录
       SCAN      + EventKey=<scene>           ← 已关注用户扫码登录
       unsubscribe                            ← 取关标记
  └─ 按 openid upsert User（username = 微信昵称派生）→ 标记登录成功
```

- `AuthProvider` 接口统一：`PasswordProvider`（一期）+ `WeChatMpProvider`（二期）；登录页标签随配置显示。
- 微信资质：认证服务号（企业主体）、备案域名、回调 80/443；access_token 集中缓存刷新。

---

## 6. 权限执行架构（后端）

- `api/deps.py`（新文件）：
  - `get_current_user` → 解析 token 加载 User + TeamMember
  - `require_roles("admin", "creator")` → 403 拦截
  - `require_team_access(novel_id=...)` → 资源归属校验（超管跳过）
  - `AUTH_ENABLED=false` 时全部退化为 no-op（行为与今天完全一致）
- 12 个现有 router 全部挂载权限依赖（最小侵入：每个路由一行依赖）。
- 团队隔离规则：所有列表/详情/搜索按 `team_id` 过滤；写操作校验 `novel_id` 归属；媒体库/全局资产按团队过滤；查看者 POST/PATCH/DELETE → 403。
- 超管维度：`is_super_admin` 不附加 `team_id` 过滤，可访问全部团队。

---

## 7. 模型配置分层（官方 vs 团队）与 Key 保护

- 数据面：`AiModelConfig.scope + team_id`；官方配置即超管维护的配置（超管设置页 = 官方配置管理）。
- 团队模式：`Team.model_config_source`：
  - `official`：团队只读官方配置列表（**响应不返回 `api_key`**），直接用。
  - `custom`：团队管理员在设置页增删改本团队配置；**团队管理员可见本团队 Key**（D4 已确认）。
- 模型解析（运行时唯一事实来源）：`resolve_models(team)` → 团队自定义启用项优先，否则官方启用配置；规则集中 `services/model_resolution.py`。
- **Key 保护红线**：官方配置 `api_key` 对超管以外任何角色一律不出现在 API 响应（序列化层统一剥离 + 测试钉死）；二期数据库加密存储（`cryptography`，引入前确认依赖）。

---

## 8. 余额与计费改造

- `BalanceTransaction` 流水（充值/消费/调整）不可变，`balance_after` 冗余余额用于对账。
- 充值/调整：仅超管，团队管理页操作。
- 消费：`record_ai_task_usage` 落 `ModelUsageRecord` 后同事务原子条件扣减 `UPDATE teams SET balance = balance - ? WHERE id=?`；流水记 `usage_record_id`。
- 欠费拦截：`ai_task_executor.submit` 前置检查 `balance <= 0` → 拒绝 + 明确错误码。
- 透支策略（D3）：并发下允许透支为负 → 团队管理页/成本看板标红；欠费禁新任务；预留 `STRICT` 模式（二期）。
- 计费聚合：`services/billing/aggregation.py` 增加 `team_id` / `user_id` 过滤；`/billing/*` 按角色强制作用域（管理员=团队全部，创作者=本人，查看者 403）。
- 成本看板：管理员可筛选成员；创作者固定本人。

---

## 9. 前端设计

- auth 基座：`useAuthStore`（user/membership/permissions）、路由守卫（`meta.roles`）、fetch 拦截器（注入 token、401 跳登录）。
- 页面：
  - `LoginPage`：一期账号密码（二期加微信扫码标签页，随配置显示）
  - `MembersPage`（团队管理员）：成员列表、创建账号/初始密码、角色调整、移除成员
  - `TeamsPage`（超管）：团队列表/创建/停用、余额充值记录、官方模型配置入口
  - `SettingsPage` 改造：官方模式（只读列表 + "当前使用官方配置"横幅）vs 自定义模式
  - `BillingPage` 改造：角色作用域 + 成员筛选
- 侧边导航按权限渲染：创作者/查看者隐藏「设置」「成本」；团队管理员多「成员管理」；超管多「团队管理」。
- 路由：`/login`（公开）、`/members`（团队管理员）、`/teams`（超管），守卫按角色重定向。
- 关闭开关时：登录页/成员/团队路由不注册，侧边栏与今天一致。

---

## 10. 部署与配置

- 新增环境变量（`.env.example` 同步，密钥不进仓库）：
  - `AUTH_ENABLED`（默认 `false`）
  - `SESSION_TTL_HOURS`、`SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD`
  - `WECHAT_MP_APP_ID / WECHAT_MP_APP_SECRET / WECHAT_MP_TOKEN / WECHAT_MP_AES_KEY`（二期）
  - `DB_KEY_ENCRYPTION_SECRET`（二期）
- **docker-compose 默认 `AUTH_ENABLED=false`**：开源用户行为不变；线上部署在 `.env` 里开启并配置超管账号。
- 线上：自建服务器 + 域名 + HTTPS 反代（nginx/caddy 示例配置随文档提供；二期微信回调需要公网 80/443）。
- 媒体文件：`/media` 静态直链 v1 可接受（URL 不可猜测）；二期鉴权下载接口。

---

## 11. 分阶段实施（每阶段独立可测、可合并，全部在当前仓库）

| 阶段 | 内容 |
|---|---|
| **P0 开关基建** | `AUTH_ENABLED` 配置、main.py 条件注册（模型/路由/种子）、compose 默认关闭、vanilla 回归基线（现有测试原样通过） |
| **P1 认证基座** | auth 模型 + deps + 密码登录（服务/API/超管 bootstrap/登录页）+ AuthProvider 接口预留微信 |
| **P2 团队隔离** | Novel/usage_record/媒体库 加列、查询过滤、资源归属校验、存量回填迁移 |
| **P3 RBAC 执行** | 12 个路由挂权限依赖、角色矩阵参数化测试、查看者写拦截 |
| **P4 前端权限** | auth store、路由守卫、导航过滤、401 处理 |
| **P5 模型配置分层** | scope/mode、官方配置管理、Key 剥离序列化、`resolve_models` |
| **P6 余额计费** | BalanceTransaction、充值/消费/欠费拦截、聚合作用域、成本页角色过滤 |
| **P7 管理页面** | 成员管理（账号/角色/移除）、团队管理（创建/余额/停用） |
| **P8 加固与微信上线** | 微信扫码接入、密钥加密、审计日志（余额/权限变更）、部署文档、全量回归 |

---

## 12. 测试策略

- **vanilla 基线（关闭态）**：`AUTH_ENABLED=false` 时现有测试套件原样通过 —— 这是每次改动的回归红线。
- **RBAC 矩阵参数化测试**：每角色 × 每路由 × 每方法，断言 200/403 与数据可见性。
- **认证流测试**：密码登录（登录/登出/改密/会话过期/吊销）、微信回调全链路 mock（一期先测 Provider 接口契约）。
- **余额原子性**：并发扣减、透支、欠费拦截、流水对账。
- **Key 保护测试**：任何角色（含团队管理员）拉取官方配置，断言响应无 `api_key`。
- 前端：守卫/导航渲染/登录页测试沿用 Vitest 惯例。

---

## 13. 风险与开放问题

1. **公开可见性**：单仓方案下鉴权/团队/余额代码随仓库公开（CC BY-NC 4.0），商业价值定位需确认（见 §1.2）。
2. **微信资质**：认证服务号（企业主体）+ 备案域名决定 P8 时间；一期密码登录不受影响。
3. **成员加入方式**：v1 由管理员创建账号发初始密码；微信上线后扫码自动注册 + 邀请码入队。
4. **官方配置混合粒度**：v1 全局二选一（official/custom），二期可考虑按任务类型混配。
5. **审计日志范围**：至少覆盖余额变更、角色变更、团队创建/停用（P8 实施）。
6. **媒体文件鉴权**：v1 沿用静态直链，确认可接受。
7. **开关两态回归成本**：新增代码必须同时过 vanilla + 开启态测试，CI 双跑固化。

---

## 14. 与本项目既有约束的对齐

- 分阶段提交、`type(scope): description` 提交信息；默认在 `develop` 分支开发。
- 改动全部失败测试先行 + 定向回归；前端过 typecheck + build，后端过 pytest。
- 无限画布工作台与 `/Users/anning/Projects/shengshimedia` 的兼容约束不受影响（P3 路由鉴权改动后跑全量回归确认画布行为不变）。
- 新增依赖需确认：密码用 stdlib pbkdf2，微信协议用现有 httpx 手写；二期 `cryptography` 引入前确认。
- 关闭开关时行为与现状一致，不改变现有任何接口契约与数据表结构。
