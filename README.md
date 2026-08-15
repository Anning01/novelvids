<p align="center">
  <img src="docs/images/logo.png" width="200" alt="猫影短剧 Logo">
</p>

<h1 align="center">猫影短剧</h1>

<p align="center">
  <strong>「 AI 驱动的小说转短剧全流程生产平台 」</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-00584c?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Vue_3-42B883?style=for-the-badge&logo=vuedotjs&logoColor=white" alt="Vue 3">
  <img src="https://img.shields.io/badge/Python_3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript">
  <img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white" alt="Vite">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</p>

<p align="center">
  <a href="#成品视频示例">成品视频示例</a> &bull;
  <a href="#核心功能">核心功能</a> &bull;
  <a href="#界面预览">界面预览</a> &bull;
  <a href="#快速开始">快速开始</a> &bull;
  <a href="#模型配置">模型配置</a> &bull;
  <a href="#项目结构">项目结构</a> &bull;
  <a href="#技术栈">技术栈</a> &bull;
  <a href="#测试">测试</a>
</p>

---

## 介绍

**猫影短剧** 是一个开源的 AI 短剧生产平台。输入一部小说，即可自动完成
**章节拆分 → 实体提取 → 参考图生成 → 分镜生成 → 视频合成** 的全流程，把文字小说变成带画面的短剧。

本项目不是 demo 或 proof-of-concept，而是拥有完整工程架构、严格分层设计与全面测试覆盖、可直接部署使用的生产级应用。

## 成品视频示例

一段由猫影短剧从小说自动生成的短剧成品片段：

<!--
  TODO(成品视频)：请替换为真实的成品视频。可任选其一：
  1) 上传 GIF/MP4 到 docs/videos/ 目录，并在下方引用（README 建议用 GIF 或外链，GitHub 不渲染 <video>）；
  2) 使用外链平台（B 站 / YouTube / 优酷），放一张封面缩略图并点击跳转。
-->

[![成品视频示例封面](docs/videos/demo-cover.png)](https://your-video-link.example.com)

> 点击上方封面观看完整片段。生成链路：上传小说 → 章节拆分 → 实体提取 → 参考图生成 → 分镜生成 → 逐镜头视频合成。

## 核心功能

### 小说管理
- 小说录入与元数据管理（名称、作者、简介、封面）
- **AI 智能章节拆分** —— 自动识别章节边界，一键拆分长篇小说
- 章节级别的工作流状态追踪

### 短剧生产工作流
每个章节拥有独立的多步工作流，环环相扣：

| 步骤 | 功能 | 说明 |
|:---:|------|------|
| **1** | 实体提取 | AI 分析章节内容，自动提取角色、场景、道具等实体 |
| **2** | 资产管理 | 管理提取的实体资产，AI 生成角色/场景参考图 |
| **3** | 分镜生成 | AI 将章节内容转化为分镜脚本，生成每个镜头的提示词 |
| **4** | 视频合成 | 基于分镜与参考图，调用视频生成模型产出短剧片段 |

### 无限画布工作台
- 基于 Vue Flow 的分镜画布，支持平移/框选、缩放、自动布局、节点选择、复制/粘贴、撤销/重做、折叠、标记与视口持久化
- 故事版（分镜列表）与画布工作流共用同一份资产引用数据，两端编辑一致

### 多模型支持
- 灵活的 AI 模型配置系统，支持多任务类型独立配置
- 每种任务类型（文本生成、图像生成、视频生成）可配置不同模型
- 模型热切换 —— 一键激活/停用，无需重启

### 资产库与视频库
- 全局资产/视频管理，查看所有项目的生成结果
- 实时状态追踪（排队中/处理中/已完成/失败）
- 支持预览与批量管理

## 界面预览

<!--
  TODO(截图)：以下图片为占位。运行项目后逐页截图，保存到对应路径，
  替换后删除本注释。截图清单见下一小节。
-->

<table>
  <tr>
    <td align="center"><b>首页</b></td>
    <td align="center"><b>项目列表</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/screenshots/home.png" alt="首页" width="480"></td>
    <td><img src="docs/images/screenshots/projects.png" alt="项目列表" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>小说详情</b></td>
    <td align="center"><b>短剧智能流程</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/screenshots/novel.png" alt="小说详情" width="480"></td>
    <td><img src="docs/images/screenshots/agent.png" alt="短剧智能流程" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>分镜编辑（故事版）</b></td>
    <td align="center"><b>无限画布工作流</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/screenshots/storyboard.png" alt="分镜编辑" width="480"></td>
    <td><img src="docs/images/screenshots/workbench.png" alt="无限画布工作流" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>视频生成</b></td>
    <td align="center"><b>模型配置</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/screenshots/video.png" alt="视频生成" width="480"></td>
    <td><img src="docs/images/screenshots/settings.png" alt="模型配置" width="480"></td>
  </tr>
</table>

### 截图清单（待补充）

将以下页面截图保存到对应路径，即可自动替换上面的占位图：

| 截图文件 | 对应页面 / 路由 |
|------|------|
| `docs/images/screenshots/home.png` | 首页 `/` |
| `docs/images/screenshots/projects.png` | 项目列表 `/projects` |
| `docs/images/screenshots/novel.png` | 小说详情 `/novel/:id` |
| `docs/images/screenshots/agent.png` | 短剧智能流程 `/create/short-drama/agent/:projectId` |
| `docs/images/screenshots/storyboard.png` | 分镜编辑 `/create/short-drama/storyboard/:projectId` |
| `docs/images/screenshots/workbench.png` | 无限画布工作流 `/novel/:novelId/chapter/:chapterId/step/:stepId` |
| `docs/images/screenshots/video.png` | 视频生成 `/create/short-drama/video/:projectId` |
| `docs/images/screenshots/settings.png` | 模型配置 `/settings` |

## 快速开始

### 环境要求

- Docker 20.10+（含 Docker Compose）
- 或本地开发：Python 3.12+、Node.js 20+、[uv](https://docs.astral.sh/uv/)

### 方式一：Docker 部署（推荐）

```bash
# 克隆项目
git clone https://github.com/Anning01/novelvids.git
cd novelvids

# 一键构建并启动（前端 + 后端）
docker compose up -d --build
```

启动完成后：

- 访问应用：<http://localhost:8080>
- 访问 API 文档：<http://localhost:8080/docs>
- 数据持久化在 `./data`（SQLite 数据库）与 `./media`（生成的图片/视频）目录

> 首次启动后，请先到「设置 / 模型配置」页填入你的 AI 模型 API Key（见[模型配置](#模型配置)），再开始生成。

停止 / 更新：

```bash
docker compose down          # 停止并删除容器（数据保留在 ./data 与 ./media）
docker compose up -d --build # 重新构建并启动
```

### 方式二：本地开发

#### 后端

```bash
# 安装依赖（使用 uv，保留 uv.lock）
uv sync --dev

# 启动后端（默认 0.0.0.0:9000，与前端代理配置一致）
make dev PORT=9000
```

#### 前端

```bash
cd web

# 安装依赖（使用 package-lock.json）
npm ci

# 启动开发服务器（自动代理 /api 与 /media 到后端）
npm run dev
```

访问 <http://localhost:3000> 即可使用。

## 模型配置

AI 模型配置保存在数据库中，通过 Web 界面的「**设置 / 模型配置**」页（`/settings`）进行增删改与启停，无需改动环境变量。

按任务类型配置，支持三类模型：

### 文本模型（实体提取 / 分镜 / 项目分析）

采用 **OpenAI 兼容协议**，可接入 OpenAI、DeepSeek、豆包、月之暗面等：

| 字段 | 说明 |
|------|------|
| 名称 | 配置显示名，如 `deepseek-v3` |
| API 地址 | 供应商 base_url，如 `https://api.deepseek.com/v1` |
| API Key | 你的密钥 |
| 模型名称 | 如 `deepseek-chat` |
| 接口协议 | `openai_compatible` |
| 支持 JSON 输出 | 分镜等结构化任务建议开启 |

### 图像模型（参考图生成）

| 模型类型 | 说明 | 协议 |
|------|------|------|
| Doubao Seedream 5.0 Lite / Pro | 豆包生图 | `volcengine_ark` / `openrouter_compatible` |
| GPT Image 2 | OpenAI 生图 | `openai_compatible` / `openrouter_compatible` |

### 视频模型（视频合成）

| 模型类型 | 说明 | 协议 |
|------|------|------|
| Doubao Seedance 2.0 / 2.0 Fast / 2.0 Mini / 2.5 | 豆包视频生成 | `volcengine_ark` |

> 每种任务类型可配置并同时启用多个模型，通过「启用/停用」一键热切换。

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
│   ├── image_generation/   # 生图能力与协议适配
│   ├── video/              # 视频生成服务（Seedance 等）
│   └── ...
├── prompts/                # Prompt 模板 —— 集中存放，禁止内联大段文本
├── seeds/                  # 种子数据（音频、数字人）
├── scripts/                # 运维脚本（如资产引用回填）
├── test/                   # 后端测试套件（api/controllers/models/services）
│
├── web/                    # 前端应用 —— Vue 3 + TypeScript + Vite
│   ├── src/
│   │   ├── pages/          # 页面组件
│   │   ├── features/workbench/  # 无限画布工作台
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
├── pyproject.toml          # Python 项目配置
└── README.md
```

## 技术栈

### 后端

| 技术 | 用途 |
|------|------|
| **FastAPI** | 高性能异步 Web 框架 |
| **Tortoise ORM** | 异步 ORM，支持 SQLite / PostgreSQL |
| **Pydantic** | 数据校验与序列化 |
| **OpenAI SDK** | AI 模型统一调用接口 |
| **Uvicorn** | ASGI 服务器 |
| **uv** | 依赖与虚拟环境管理 |

### 前端

| 技术 | 用途 |
|------|------|
| **Vue 3** | UI 框架（Composition API） |
| **TypeScript** | 类型安全 |
| **Vite** | 构建工具 |
| **Pinia** | 状态管理 |
| **Vue Flow** | 无限画布工作台 |
| **Vue Router** | 路由管理 |
| **Vitest** | 单元测试 |

## 测试

后端使用 pytest（含覆盖率报告），前端使用 Vitest：

```bash
# 后端全部测试
uv run pytest

# 后端定向测试
uv run pytest test/test_services/test_storyboard_handler.py -q

# 前端全部测试
cd web && npm run test

# 前端类型检查与构建
cd web && npm run typecheck && npm run build
```

---

<p align="center">
  <sub>Built with passion by <a href="https://github.com/Anning01">Anning</a></sub>
</p>
