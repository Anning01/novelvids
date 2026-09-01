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
  <img src="https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey?style=for-the-badge" alt="License: CC BY-NC 4.0">
</p>

<p align="center">
  <a href="#成品视频示例">成品视频示例</a> &bull;
  <a href="#在线演示">在线演示</a> &bull;
  <a href="#核心功能">核心功能</a> &bull;
  <a href="#界面预览">界面预览</a> &bull;
  <a href="#快速开始">快速开始</a> &bull;
  <a href="#模型配置">模型配置</a> &bull;
  <a href="#数据库与媒体存储">数据库与媒体存储</a> &bull;
  <a href="#项目结构">项目结构</a> &bull;
  <a href="#技术栈">技术栈</a> &bull;
  <a href="#测试">测试</a> &bull;
  <a href="#许可协议">许可协议</a>
</p>

---

## 介绍

**猫影短剧** 是一个开源的 AI 短剧生产平台。输入一部小说，或上传已有视频作为重制来源，即可自动完成
**章节拆分 / 视频理解 → 实体提取 → 设定资产生成 → 分镜生成 → 多模态视频生成 → 章节成片合并** 的全流程，把文字小说或参考成片变成可持续生产的短剧项目。

平台同时提供 Agent 与人工编辑两种创作方式，支持分镜策略、角色衍生形态、角色/旁白音色、首尾帧连续生成、批量无人值守生成，以及 Seedance、MiniMax H3、Wan3 等视频模型的统一适配。

本项目不是 demo 或 proof-of-concept，而是拥有完整工程架构、严格分层设计与全面测试覆盖、可直接部署使用的生产级应用。

## 在线演示

- 地址：<https://demo.xiazq.com>
- 用户名：`demo`
- 密码：`NovelVids-Demo-2026`
- 权限：演示团队查看者，可浏览项目、设定、分镜、图片和已有视频；写操作由后端 RBAC 拒绝
- 数据：团队余额与个人额度均为 0，不配置模型 Key，不使用 OSS；每天北京时间 `00:00` 恢复黄金快照（包括被修改的演示密码）
- API 文档：<https://demo.xiazq.com/docs>（仅演示站开放；正式商业站默认建议关闭）

演示站与商业环境完全隔离，使用独立数据库和本地媒体副本，并启用应用与反向代理双层登录限流、安全响应头、可信代理校验和每日原子还原。请勿在演示站上传隐私或生产数据。

## 成品视频示例

一段由猫影短剧从小说自动生成的短剧成品片段：

<!--
  TODO(成品视频)：把完整视频上传到 B 站 / YouTube / 优酷后，把下方链接替换为真实地址。
-->

[![成品视频示例封面](docs/videos/demo-cover.jpg)](https://youtu.be/fdiw__J19uk)

![成品视频高光预览](docs/videos/demo-preview.gif)

> 点击封面观看完整片段。生成链路：上传小说 → 章节拆分 → 实体提取 → 参考图生成 → 分镜生成 → 逐镜头视频合成。

## 核心功能

### 从书稿到项目

- 支持粘贴文本和上传 `doc`、`docx`、`txt`、`pdf`，自动解析正文与章节结构
- Agent 模式自动完成项目分析、章节拆分与资产规划；人工模式可逐步编辑
- 项目比例、分辨率、视觉风格和分镜策略在创建时确定，并在后续页面保持一致
- 浅色/深色主题拥有独立创作页背景，界面设置本地持久化

### 重制工坊

- 支持上传单个 `mp4` / `mov` 视频、按集数命名的整套文件夹，以及选择系统内的历史项目
- 单视频最大 500 MB、最长 20 分钟；文件夹模式自动识别“第12集 / 第12话 / EP12 / E12 / 12集”等集数格式并排序
- 创建时可选择比例、清晰度和视觉风格，入口与短剧制作复用同一套创作 UI
- 后端先识别全局角色、场景和道具，再检测镜头并逐段生成专业分镜 Prompt，最终写入现有设定页、故事版与无限画布
- 拆解任务在服务端异步运行；关闭或刷新页面不会取消任务，重新进入项目可从持久化快照恢复进度
- 独立进度页通过 SSE 展示逐集、逐阶段和逐镜头进度，失败集可单独重试，成功集无需重复上传
- 视频理解模型仍作为 LLM 的“重制”能力用途配置；支持豆包关闭思考模式、受控并发、10 分钟单请求超时与安全耗时记录

### 设定资产与衍生形态

- 自动提取角色、场景、道具，并将同一实体的别名统一归档
- 角色、场景、道具三类资产可在一次批量任务中同时生成
- 支持文生图、上传图片、从音色库选择，以及参考图驱动的图生图
- 每个资产保留生成历史和当前版本；支持图片放大预览、切换当前版本与生成状态反馈
- 支持角色变装、年龄/状态变化等衍生形态；每个衍生形态可独立配置图片和音色
- 支持资产合并与章节级资产绑定，故事版与无限画布共享同一份引用关系

### 分镜策略与专业 Prompt

- 分镜策略工厂：内置「电影感叙事」和「旁白叙事」，项目创建和剧本编辑均可切换
- 旁白策略可配置统一旁白音色，并在无人物对白的时间段安排旁白或人物内心 OS
- 每个视频 Prompt 都是可独立执行的镜头任务：完整写明时间、环境、站位、动作起止和声音
- 最终 Prompt 使用 `@{资产名}` 与 `@音频N` 显式绑定角色、场景、道具和角色音色
- 高优先级核心生成指令会前置初始画面、动作、人声和同步音效，再保留详细时间轴
- 分镜 Prompt 可视化编辑，资产/音频标签可点击预览或播放；遗漏实体引用会自动补标

### 故事版与无限画布

- 故事版集中编辑分镜描述、资产、Prompt、视频参数与生成状态
- 基于 Vue Flow 的无限画布支持平移、框选、缩放、自动布局、复制/粘贴、撤销/重做、折叠、标记与视口持久化
- 无限画布可拖入参考图，接口与故事版共用多模态素材协议
- 分镜选择的模型、比例与分辨率会持久化，刷新页面不会恢复成其他模型

### 音色库与声音一致性

- 内置系统音色，同时支持用户上传 `mp3` / `wav` 参考音频
- 展示真实音频时长；长音频可通过双滑块在线裁剪并从裁剪起点试听
- 角色基础形态、每个衍生形态和项目旁白均可独立选择音色，选择后立即保存
- Prompt 中明确写出 `@音频N 对应角色 @{角色名}`，避免模型混淆声音归属
- Seedance 支持 `asset://`、公网 URL 与本地 Base64；MiniMax 使用公网 URL/Base64；Wan3 的本地素材通过阿里云百炼临时存储处理

### 视频生成、连续性与成片

- 配置驱动的视频工厂，根据模型能力自动转换请求参数，不依赖模型名称猜测
- 支持参考生视频和首尾帧生视频；参考图片、视频、音频均有明确用途
- 单镜头可设置模型、时长、比例、分辨率、声音和尾帧衔接
- 批量生视频可统一模型、比例、分辨率并选择多个分镜；开启尾帧连续生成后按顺序逐个执行，无需值守
- 供应商未返回尾帧时，后端通过 FFmpeg 从成片提取；下一镜头自动把该图片作为首帧参考
- 异步任务由后端定时收口，关闭浏览器或刷新页面后仍会继续查询供应商结果
- 章节成片按分镜顺序合并当前已有视频，可直接下载合并后的完整视频，而非单个分镜
- 全局媒体库支持图片、视频、音频预览和生成版本管理

### 多模型与成本计费

- 文本、图像、视频任务分别配置模型，支持多个配置并行启用与页面选择
- 模型能力、默认参数、素材限制、协议和价格以后端配置为唯一事实来源
- 每次调用记录 token、张数/秒数、输入素材、定价快照、折扣、金额和请求时长
- 支持模型级折扣与优惠前后价格展示；MiniMax H3 支持按输出秒数和输入图片/视频分别计费
- 成本看板支持项目过滤、汇总与分页流水；团队模式支持余额预检和完成后扣费

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
    <td align="center"><b>资产管理</b></td>
  </tr>
  <tr>
    <td><img src="docs/images/screenshots/novel.png" alt="小说详情" width="480"></td>
    <td><img src="docs/images/screenshots/asset.png" alt="资产管理" width="480"></td>
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
  <tr>
    <td align="center" colspan="2"><b>成本看板</b></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/images/screenshots/billing.png" alt="成本看板" width="960"></td>
  </tr>
</table>

## 快速开始

### 环境要求

- Docker 20.10+（含 Docker Compose）
- 或本地开发：Python 3.12+、Node.js 20+、[uv](https://docs.astral.sh/uv/)
- FFmpeg / ffprobe（章节视频合并、重制镜头切分、模型输入准备、媒体探测和尾帧兜底提取）

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
- 默认数据持久化在 `./data`（SQLite 数据库）与 `./media`（图片、视频、音频）目录；生产环境可通过环境变量切换 PostgreSQL 与阿里云 OSS

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

## 登录与团队功能（可选开关）

项目内置一套**开关式**登录与团队能力，默认关闭 —— docker 部署即用，与无鉴权版本完全一致：

- 设置环境变量 `AUTH_ENABLED=true` 后，必须登录才能使用，并默认启用团队功能：
  - 四级角色：超级管理员 / 团队管理员 / 创作者 / 查看者
  - 团队数据隔离、成员管理、团队管理（余额充值）
  - 模型配置支持「官方配置」（Key 不可见）与「团队自定义」
  - 团队余额：任务提交预检 + 完成自动扣费，欠费拦截
  - 一期为账号密码登录（`SUPER_ADMIN_USERNAME/PASSWORD` 引导超管），微信公众号扫码登录为二期接入点
- 完整部署说明（环境变量、HTTPS 反代示例、微信接入点）见 [docs/team-auth-deployment.md](docs/team-auth-deployment.md)

## 模型配置

AI 模型配置保存在数据库中，通过 Web 界面的「**设置 / 模型配置**」页（`/settings`）进行增删改、定价、折扣与启停，无需把供应商密钥写入源码。按任务类型配置，支持三类模型：

### LLM 大模型（实体提取 / 分镜 / 项目分析 / 重制拆解）

采用 **OpenAI 兼容协议**，可接入 OpenAI、DeepSeek、豆包、月之暗面等。一个模型可同时勾选多个“能力用途”；只有支持视频输入的多模态模型才应勾选“重制”：

| 字段 | 说明 |
|------|------|
| 名称 | 配置显示名，如 `deepseek-v3` |
| API 地址 | 供应商 base_url，如 `https://api.deepseek.com/v1` |
| API Key | 你的密钥 |
| 模型名称 | 如 `deepseek-chat` |
| 接口协议 | `openai_compatible` |
| 支持 JSON 输出 | 分镜等结构化任务建议开启 |
| 能力用途 | 可多选内容理解、分镜规划、项目分析、重制；“重制”要求模型支持视频输入 |
| 思考模式 | 可按模型配置开启或关闭；豆包关闭时使用方舟兼容的 `thinking=disabled` |
| 并发与超时 | 重制镜头并发读取模型配置；单次视频理解请求最长等待 10 分钟 |

### 图像模型（参考图生成）

| 模型类型 | 说明 | 协议 |
|------|------|------|
| Doubao Seedream 5.0 Lite / Pro | 豆包生图 | `volcengine_ark` / `openrouter_compatible` |
| GPT Image 2 | OpenAI 生图 | `openai_compatible` / `openrouter_compatible` |

### 视频模型（视频合成）

视频请求统一进入模型工厂，再由所选配置的 `video_model_type` 选择适配器并校验素材、时长、比例、分辨率与接口协议。

| 模型类型 | 主要能力 | 协议 |
|------|------|------|
| Doubao Seedance 2.0 / Fast / Mini | 参考图/视频/音频、首尾帧、同步声音，最长 15 秒 | `volcengine_ark` |
| Doubao Seedance 2.5 | 更多参考素材、最长 30 秒、系统音频素材 `asset://` | `volcengine_ark` |
| MiniMax H3 | 768P / 2K、参考图/视频/音频、首尾帧 | `minimax` |
| Wan3 | 文生/图生/首尾帧/全能参考，支持百炼临时素材上传 | `dashscope` |

> 每种任务类型可同时启用多个配置。前端只展示当前模型实际支持的参数；供应商不返回尾帧时由 FFmpeg 兜底，不需要在适配器中伪造能力。

## 数据库与媒体存储

数据库和媒体存储完全通过环境变量选择，不需要修改业务代码。可复制 [`.env.example`](.env.example) 为 `.env` 后按环境填写；不要提交真实密钥。

### SQLite 与 PostgreSQL

开发环境默认使用 SQLite：

```dotenv
DATABASE_URL=sqlite://./data/novelvids.db
```

生产环境可切换 PostgreSQL：

```dotenv
DATABASE_URL=postgres://novelvids:your-password@127.0.0.1:5432/novelvids
```

应用启动时会以 `safe=True` 创建缺失表并执行兼容初始化，不会删除已有表。正式迁移数据前仍应备份数据库并在停写窗口执行迁移。

### 本地媒体与阿里云 OSS

默认媒体文件写入本地目录：

```dotenv
MEDIA_PATH=./media
OSS_PROVIDER=local
```

启用阿里云 OSS：

```dotenv
OSS_PROVIDER=aliyun
OSS_BUCKET=your-bucket
OSS_ENDPOINT=oss-cn-guangzhou.aliyuncs.com
OSS_INTERNAL_ENDPOINT=oss-cn-guangzhou-internal.aliyuncs.com
OSS_PUBLIC_BASE=https://media.example.com
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
```

- 浏览器通过签名策略直传大文件，避免书稿、参考视频和音频绕行应用服务器
- 服务端下载、裁剪、章节合并、尾帧提取及再次上传统一使用 `OSS_INTERNAL_ENDPOINT`
- 对外提交给模型和浏览器预览时使用公网地址或签名 URL；数据库尽量保存稳定对象 key
- `OSS_PUBLIC_BASE` 可填写 CDN/CNAME；留空时使用 Bucket 与公网 Endpoint 组合地址

项目封面会保留原图，并自动生成列表缩略图与详情预览图。升级已有环境后，执行一次幂等回填：

```bash
uv run python scripts/backfill_media_derivatives.py
```

本地媒体会在原图旁生成 WebP 派生图；OSS 模式通过 `OSS_INTERNAL_ENDPOINT` 读写，并为派生图设置长期不可变缓存。该命令也会为设定资产图片生成缩略图，并为历史生成视频提取首帧海报。

### 视频任务自动收口

```dotenv
VIDEO_RECONCILE_INTERVAL_SECONDS=30
VIDEO_RECONCILE_BATCH_SIZE=50
```

后端会持续查询排队中和生成中的供应商任务。即使用户关闭故事版页面，任务完成、计费、尾帧提取与下一镜头注入仍会继续执行。

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

## 许可协议

本项目采用 [知识共享 署名-非商业性使用 4.0 国际许可协议（CC BY-NC 4.0）](LICENSE) 授权。

- ✅ **学习、研究、个人使用**：免费，无需授权。
- ✅ **转载、引用、二次开发（非商用）**：允许，但必须署名（保留原作者与项目链接）。
- ❌ **商业使用**：禁止。任何将本项目或其衍生作品用于直接或间接商业目的（包括但不限于售卖、SaaS 化对外提供服务、付费定制、广告盈利等），均需事先取得作者的**书面授权**。
- ⚠️ **未经授权商用，将依法追究法律责任。**

> 需要商用授权？请联系作者 📫 Email: anningforchina@gmail.com 洽谈。

---

<p align="center">
  <sub>Built with passion by <a href="https://github.com/Anning01">Anning</a></sub>
</p>
