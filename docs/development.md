# 开发指南

[返回首页](../README.md) · [English](development.en.md)

## 环境要求

- Python 3.12+、uv，使用仓库的 `uv.lock`。
- Node.js 22.12+（或已安装 Vite 声明的兼容范围）、npm，使用 `web/package-lock.json`。
- 后端 PATH 中有 FFmpeg 和 ffprobe，用于视频探测、切分、合并、尾帧与高清化。
- 默认 SQLite，也可配置 PostgreSQL；模型 API 需另外配置。

## 本地启动

### 后端

```bash
# 安装依赖（使用 uv，保留 uv.lock）
uv sync --dev

# 启动后端（默认 0.0.0.0:9000，与前端代理配置一致）
make dev PORT=9000
```

### 前端

```bash
cd web

# 安装依赖（使用 package-lock.json）
npm ci

# 启动开发服务器（自动代理 /api 与 /media 到后端）
npm run dev
```

访问 <http://localhost:3000> 即可使用。

## 项目结构

```
novelvids/
├── api/                    # API 层 —— RESTful 接口定义（/api 前缀）
├── controllers/            # 控制层 —— 业务逻辑编排
├── models/                 # 数据模型层 —— Tortoise ORM 模型
├── schemas/                # 数据校验层 —— Pydantic Schemas
├── services/               # 服务层 —— AI/图像/视频等外部能力调用
│   ├── ai_task_executor.py # AI 任务调度执行器
│   ├── extraction/         # 实体提取服务
│   ├── storyboard/         # 分镜生成服务
│   ├── reference/          # 参考图生成服务
│   ├── remake/             # 重制工坊上传、拆解、SSE 进度、持久化与历史项目复用
│   ├── creation_agent/     # 工具循环、作用范围、记忆、上下文压缩与操作回执
│   ├── billing/            # 用量计费、缓存明细与会话汇总视图
│   ├── image_generation/   # 生图能力与协议适配
│   ├── video/              # 视频工厂、模型能力、任务收口、合并与尾帧服务
│   ├── oss/                # 本地 / 阿里云 OSS 统一存储接口
│   └── audio_references.py # 音色上传、裁剪与持久化
├── prompts/                # Prompt 模板 —— 集中存放，禁止内联大段文本
├── seeds/                  # 种子数据（音频、数字人）
├── scripts/                # 运维脚本（如资产引用回填）
├── test/                   # 后端测试套件（api/controllers/models/services）
│
├── web/                    # 前端应用 —— Vue 3 + TypeScript + Vite
│   ├── src/
│   │   ├── pages/          # 页面组件
│   │   ├── features/workbench/  # 无限画布工作台
│   │   ├── features/creation-agent/ # 助手侧栏、会话、输入、对象选择与用量组件
│   │   ├── components/     # 通用组件
│   │   ├── shared/         # 共享工具与状态
│   │   ├── api.ts          # API 调用层
│   │   └── router.ts       # 路由
│   ├── public/             # 静态资源
│   ├── index.html
│   └── package.json
│
├── Dockerfile              # 后端镜像
├── docker-compose.yml      # 一键部署编排
├── .env.example            # SQLite/PostgreSQL、OSS、鉴权等环境变量示例
├── pyproject.toml          # Python 项目配置
└── README.md
```

## 技术栈

### 后端

| 技术 | 用途 |
|------|------|
| **FastAPI** | 高性能异步 Web 框架 |
| **Tortoise ORM** | 异步 ORM，支持 SQLite / PostgreSQL |
| **asyncpg / aiosqlite** | PostgreSQL / SQLite 异步驱动 |
| **Pydantic** | 数据校验与序列化 |
| **Pydantic AI 1.66.0 / AG-UI** | 创作助手工具循环、类型化输入输出与流式事件 |
| **OpenAI SDK** | AI 模型统一调用接口 |
| **HTTPX** | Seedance、MiniMax、Wan3 等供应商请求与媒体传输 |
| **PySceneDetect** | 重制来源视频的镜头边界检测与拆分 |
| **FFmpeg** | 章节合并、音视频探测和尾帧兜底提取 |
| **Uvicorn** | ASGI 服务器 |
| **uv** | 依赖与虚拟环境管理 |

### 前端

| 技术 | 用途 |
|------|------|
| **Vue 3** | UI 框架（Composition API） |
| **TypeScript** | 类型安全 |
| **Vite** | 构建工具 |
| **Pinia** | 状态管理 |
| **Element Plus / vue-element-plus-x / AG-UI Client** | 助手会话、消息流、输入与设置组件 |
| **Vue Flow** | 无限画布工作台 |
| **Vue Router** | 路由管理 |
| **Vitest** | 单元测试 |

## 测试

在仓库根目录运行后端测试：

```bash
AUTH_ENABLED=false uv run pytest
AUTH_ENABLED=true uv run pytest test/test_auth -q --no-cov
# 定向示例
AUTH_ENABLED=false uv run pytest test/test_services/test_storyboard_handler.py -q
```

前端检查（从仓库根目录进入一次 `web`）：

```bash
cd web
npm run test
npm run typecheck
npm run build
```

## 架构与扩展入口

- `api → controllers → services/models`：分别负责协议校验、业务编排、供应商调用与数据。
- `prompts/skills/`：一套创作规则，详见[技能开发](agent-skills-workflow.md)；不要在适配器中再建立第二套生成提示词。
- `services/image_generation/`、`services/video/`：能力约束与模型适配。
- `services/video_enhancement/`：来源准备、提交、收集与结算。
- `web/src/features/workbench/`：画布交互及节点展示，故事板与画布共享项目对象。

权限测试单独运行 `AUTH_ENABLED=true uv run pytest test/test_auth -q --no-cov`。真实模型测试需要 `test/.test.env` 和明确费用预算；模拟通过不代表供应商效果通过。普通测试不要隐式使用生产密钥。

提交 PR 前执行相关回归与 `git diff --check`；前端还需类型检查、构建和 dark/light 验收。依赖变化应有明确范围，不顺带升级锁文件。

参见[贡献指南](../CONTRIBUTING.md)与[第三方声明](../NOTICE.md)。
