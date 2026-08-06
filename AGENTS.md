# AGENTS.md

## 1. 项目概览

- 项目类型：AI 驱动的小说转短剧全流程生产平台，前后端分离。
- 前端技术栈：Vue 3.5、TypeScript 6、Vite 8、Pinia 3、Vue Flow 1.48、Vitest。
- 后端技术栈：Python 3.12、FastAPI、Tortoise ORM、Pydantic、pytest，使用 uv 管理依赖。
- 数据存储：开发环境默认使用 SQLite（`data/novelvids.db`），可通过 `DATABASE_URL` 切换。
- 核心约束：无限画布与 `/Users/anning/Projects/shengshimedia` 保持兼容；同步时优先复用同一实现，避免维护两套核心逻辑。
- 业务约束：不引入商品节点；数字人仅保留纯数字人，不引入真人类型；音频与数字人种子数据仅在表为空时初始化。

## 2. 环境搭建与开发流程

### 2.1 后端

- 安装依赖：`uv sync --dev`，必须保留并使用 `uv.lock`。
- 启动开发服务：`make dev PORT=9000`，与前端代理配置保持一致。
- 新增依赖前先检查现有依赖；未经明确授权，不修改依赖版本或锁文件。

### 2.2 前端

- 安装依赖：`cd web && npm ci`，必须保留并使用 `package-lock.json`。
- 启动开发服务：`cd web && npm run dev`，默认地址为 `http://localhost:3000`。
- 类型检查：`cd web && npm run typecheck`。
- 生产构建：`cd web && npm run build`，输出目录为 `web/dist/`。

### 2.3 数据库与种子数据

- 应用启动时使用 `Tortoise.generate_schemas(safe=True)` 安全创建缺失表；不得删除现有数据文件或表。
- `seeds/audio_references.csv` 与 `seeds/digital_humans.csv` 是初始化来源；表中已有数据时必须整表跳过，不覆盖、不重复插入。
- 修改模型或兼容逻辑时，必须补充数据库初始化、旧数据兼容和重复启动测试。

## 3. 测试规范

- 后端框架：pytest；运行全部测试：`uv run pytest`。
- 后端定向测试：`uv run pytest test/具体测试文件.py -q`。
- 前端框架：Vitest；运行全部测试：`cd web && npm run test`。
- 前端定向测试：`cd web && npm run test -- src/具体测试文件`。
- 新增或修改业务行为必须添加回归测试；可度量时，新增代码覆盖率目标不低于 80%。
- 前端测试与业务文件同目录，使用 `*.test.ts`、`*.spec.ts` 或仓库已有命名惯例；后端测试放在 `test/` 对应分层目录。
- 不得通过删除、跳过测试或无依据修改预期结果来掩盖失败；真实模型测试仅可因缺少 `test/.test.env` 配置而跳过。
- 前端改动提交前至少通过相关测试、`npm run typecheck` 和 `npm run build`；后端改动至少通过相关 pytest。

## 4. 代码风格与架构

- TypeScript 保持 `strict`、`noUnusedLocals`、`noUnusedParameters` 通过；禁止无说明使用 `any`。
- Vue 组件使用 Composition API 与 `<script setup lang="ts">`；优先复用 `web/src/components/` 和工作台共享组件。
- 组件名使用 PascalCase，函数和变量使用 camelCase，常量使用 UPPER_SNAKE_CASE；避免硬编码魔法值。
- 后端遵循 `api → controllers → models/services` 分层：API 负责协议与校验，Controller 编排业务，Model 负责数据，Service 封装外部能力。
- 复杂功能优先采用模块化面向对象设计（OOD），遵循 SOLID、单一职责、关注点分离和组合优于继承。
- 将加载、校验、转换、外部调用、持久化和流程编排拆成接口清晰、可独立测试的协作对象；编排对象不得同时承载这些实现细节。
- 创建类必须对应独立职责、复用边界、替换策略或独立测试价值，禁止为了形式机械拆类。
- 新需求先检查并扩展现有通用对象和服务，避免复制逻辑、供应商特例和一次性分支。
- 对复杂流程保留清晰的数据对象与调用链，使错误能够定位到具体步骤和责任对象。
- 随项目增长，优先使用通用组件和共享服务层，不为单一功能堆叠特例。
- 除非存在无法通用表达的明确业务规则，不增加供应商/模型专属回退、分散条件分支或一次性 `if`。
- 规则、能力、价格、路径和功能开关以后端管理配置为唯一事实来源，运行时不得依赖硬编码供应商假设。
- 修改接口时同步检查 schema、调用方、错误处理与测试；不绕过现有类型和响应结构。

## 5. 操作边界与禁止行为

- 不得修改、删除或提交 `.env`、`test/.test.env` 及其他密钥文件；日志中必须脱敏 Token、密钥和用户数据。
- 未经明确授权，不修改依赖版本、锁文件、CI/CD 配置或 GitHub 工作流。
- 不提交 `node_modules/`、`web/dist/`、`.venv/`、数据库、媒体文件、日志、IDE 配置或临时文件。
- 不删除历史迁移、兼容逻辑、种子数据或核心画布代码；确需移除时先说明影响、迁移与恢复方案并等待人工确认。
- 修改鉴权、数据删除、数据迁移、密钥管理或外部计费逻辑前，先给出变更方案并标记“需人工审核”。
- 保留工作区中不属于当前任务的修改；禁止使用破坏性 Git 命令覆盖用户改动。

## 6. 提交、安全与排错

- 默认在 `develop` 分支开发；提交信息使用 `type(scope): description`，如 `fix(workbench): 修复资产引用同步`。
- 提交或推送前检查 `git diff`、运行对应测试并执行 `git diff --check`；共享分支禁止 force push。
- 外部输入必须通过 Pydantic 或等效机制校验；禁止拼接 SQL，禁止在源码中硬编码密钥。
- 调试集成问题时，先在 Service 边界记录并对比脱敏后的实际出站请求与响应，再修改实现逻辑。
- 排查顺序：复现问题 → 检查边界日志与配置 → 编写失败测试 → 修复最小根因 → 运行定向及回归测试。
