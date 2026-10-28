[English documentation](README.en.md) · [英文对白与角色声音指南](docs/english-production.md)

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
  <a href="#创作助手-agent">创作助手</a> &bull;
  <a href="#界面预览">界面预览</a> &bull;
  <a href="#快速开始">快速开始</a> &bull;
  <a href="#模型配置">模型配置</a> &bull;
  <a href="#数据库与媒体存储">数据库与媒体存储</a> &bull;
  <a href="#prompt-与规则定制开发者">Prompt 定制</a> &bull;
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

创作助手基于 **Pydantic AI** 调用真实业务工具。你可以直接描述想新增的角色、要调整的画面或需要查询的分镜，助手在授权范围内读取项目、修改设定与提示词，并返回可检查、可撤销的操作记录。

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

### 视频画质增强（AI MediaKit）

1. 在设置的「视频画质增强」中填写具备 AI MediaKit 权限的 Key，核对价格后启用；仍需启用创作助手及支持工具调用的助手模型。图片/视频生成配置与增强配置相互独立。运行时从模型配置表读取 Key、地址和价格，不读取 `MEDIA_KIT_KEY`；此前 `.env` 只用于本地验收时取用密钥，上线无需添加该环境变量。
2. 单条视频：分镜预览保留「高清化」入口。无限画布从视频输出端口拖线到空白处，选择「高清视频」，直接创建新视频卡片，卡片使用画布深色背景，中央仅保留清晰度选择与增强操作；服务选择收进选中工具栏。确认费用后，进度与完成视频也在该卡片显示，无须中间转换器或导出弹窗。提交后来源、服务与清晰度锁定，连线和撤销不能改写任务；换参数请删除卡片或重新拉线创建，删除卡片不会删除已保存的视频。无需等待其他分镜或整集完成；整集成片仍在视频页准备。
3. 仅允许清晰度提升：按真实文件短边检查，禁止1080p→1080p或降级。画布可选后台启用并配置价格的720p、1080p、2K、4K档位。旧配置继续保留原1080p档位；在设置中编辑增强服务、勾选新增档位并核对价格后生效。画布菜单会展示全部支持档位，并区分“服务未启用”和“不高于原片”，不会因展示选项而自动改价或启用服务。当前MediaKit大模型服务仍只接收最高1080p的原片，因此可做1080p→2K/4K，不能把2K输出继续作为输入；需要4K时直接从符合限制的原片生成。原视频保留，不自动替换分镜当前选择。
4. 核对冻结版本、目标清晰度、实际时长和费用后确认增强。保持原比例和帧率，原片与高清版分别保留；已成功增强的相同版本直接复用，重复下载不计费。也可在助手中提出需求，核对具体版本和报价后确认。
5. 后台负责查询、保存与结算；关闭浏览器不影响收集。下载失败只重试保存，不重新增强；提交结果不明时待人工核对，不自动重复收费。更换镜头后需准备新版本。

增强按供应商报告的实际时长、输出规格和管理端价格单独记录「画质增强」用量；报价不是供应商最终账单。缺少用量时标记待核对，不视为已核实零费用。应用验证输出尺寸、时长与帧率，并保留原音轨；画质、人物细节及长期稳定性仍以实际样片为准，不保证固定节省比例。

本地成片保存在 `CHAPTER_EXPORT_PATH`（默认 `./data/chapter-exports`），必须位于公开 `MEDIA_PATH` 之外；下载经过项目权限检查。默认 Docker 的 `data` 挂载已覆盖此目录，自定义路径需自行持久化和备份，不能给它配置公开静态目录。供应商通过 MediaKit 临时上传读取本地成片，无需开放本机端口；OSS沿用现有私有存储及签名地址。不要把密钥写进 Skills、任务或源码。

开发与验收的完整规则、恢复及回退说明见[开发计划](docs/superpowers/plans/2026-10-27-mediakit-video-enhancement.md)和[执行与验收记录](docs/superpowers/verification/2026-10-27-mediakit-video-enhancement.md)。支持单条已生成视频与章节成片增强。画布提供可选清晰度的新视频卡片；相同来源、服务和清晰度共用任务与结果，不自动逐镜头增强或插帧。能力与价格参考[官方API说明](https://docs.volcengine.com/docs/intelligent-processing/enhance-video-generative?lang=zh)和[官方计费说明](https://docs.volcengine.com/docs/Intelligentprocessing/video-tool-billing?lang=zh)。

### 多模型与成本计费

- 文本、图像、视频任务分别配置模型，支持多个配置并行启用与页面选择
- 模型能力、默认参数、素材限制、协议和价格以后端配置为唯一事实来源
- 每次调用记录 token、张数/秒数、输入素材、定价快照、折扣、金额和请求时长
- 支持模型级折扣与优惠前后价格展示；MiniMax H3 支持按输出秒数和输入图片/视频分别计费
- 成本看板支持项目过滤、汇总与分页流水；团队模式支持余额预检和完成后扣费
- 创作助手流水按会话汇总，展开后查看原始调用明细、失败状态与费用；保留原始用量记录，不重复计费
- 助手每轮可查看输入、输出、缓存及摘要用量；缓存价格使用当前供应商配置，未配置时明确提示

## 创作助手 Agent

### 用对话完成设定与分镜创作

- **查询、创建、修改与删除**：管理人物、场景、道具、衍生形态和分镜；按当前指定对象、章节或项目范围执行，服务端校验权限与版本
- **统一提示词规范**：复用系统的图片和分镜规范；局部修改支持精确片段替换，保留未修改的动作、声音和引用；独立分镜内的小镜头编号从 1 开始
- **长期与短期记忆**：保留近期对话；从用户原文中保存明确的持续要求，并按项目、章节、指定对象或剧情区间应用；新会话可继续使用相关规则
- **有界上下文**：按需查询对象、分页读取正文，对较早对话和已完成工具内容自动整理；原始记录保留，可检索操作依据；摘要失败时使用有界检查点继续任务
- **真实保存回执**：展示修改差异与撤销入口；重复请求不会重复写入，后续人工修改与版本冲突会阻止覆盖

助手统一编排创作设定、分镜、图片、视频与合成任务。工作区原有按钮继续保留，并与聊天使用相同的技能和执行边界；明确要求生成即授权相应的模型调用。

### 启用与使用

1. 在「设置 → 模型配置」中添加或编辑 LLM，勾选 **创作助手** 用途，并开启 **支持多轮工具调用**。
2. 在「设置 → 通用配置 → 创作助手」中启用助手并保存。开启鉴权时，全局助手配置由超级管理员管理。
3. 打开项目的设定页、故事版或工作流，点击右上角「创作助手」。也可以点击对象上的「用助手修改」，直接引用当前对象。
4. 选择修改范围并用自然语言描述要求，例如「只把这个分镜改成暖光，保留动作和声音」或「在当前章节新增一个雨夜车站场景」。
5. 通过回复下方的操作记录检查修改；需要时展开差异或撤销。顶部支持新会话、历史会话切换、删除及恢复会话。

桌面端助手与页面并排布局，打开时为侧栏让出空间。消息、查询结果、修改详情、记忆、用量和对象引用均支持折叠；模型选择位于输入区底部。折叠和运行状态动效参考 Beautiful UI，并保留[来源与许可](web/src/features/creation-agent/beautiful-ui.NOTICE.md)。

### 上下文与用量设置

以下是项目当前采用的 DeepSeek 长上下文预设，均可在「高级设置」调整；调用次数、对象数、超时和每轮总用量是本项目的运行策略，并非供应商的统一默认值。

| 设置 | 默认值 |
|------|--------|
| 工作上下文预算 | 840,000 预估输入 token |
| 上下文字符硬上限 | 2,000,000 字符 |
| 整理触发 / 目标比例 | 70% / 45% |
| 单次输出 / 每轮累计用量上限 | 64,000 / 2,000,000 token |
| 每轮模型 / 工具调用上限 | 20 / 50 次 |
| 每轮对象数 / 运行超时 | 32 个 / 600 秒 |
| 历史处理轮数参数 / 每页正文读取 | 12 轮 / 4,000 字符 |
| 摘要输出 / 等待上限 | 4,000 token / 30 秒 |

这些数值是上限，不会预先填满上下文。模型配置中更低的输出和上下文字符限制仍会生效；切换模型或代理时应按其实际能力调整。每轮累计用量包含多次调用，与单次上下文窗口不同，压缩不会退还已经消耗的用量。

完整匹配旧版默认限制的已保存配置会在读取时应用新预设；任何限制已有自定义值时保留整套配置。原始聊天记录不因压缩而删除，缓存命中与费用以供应商实际返回的用量及后台配置价格为准。

### 页面入口

应用使用 Hash 路由，下面的路径位于站点地址的 `/#` 后；`:projectId` 替换为项目 ID。

| 页面 | 路径 / 入口 | 本次更新 |
|------|-------------|----------|
| 短剧制作 / 重制工坊 | `/create/short-drama`、`/create/remake` | 统一创作入口与浅色、深色主题 |
| 设定与创作工作区 | `/create/short-drama/agent/:projectId`、`/create/short-drama/manual/:projectId` | 从设定对象直接进入助手，查询与维护创作资产 |
| 分镜故事版 / 工作流 | `/create/short-drama/storyboard/:projectId` | 并排助手侧栏、对象引用、修改回执及工作区刷新 |
| 设置 | `/settings` → 模型配置 / 通用配置 | 工具调用能力开关、扩大模型编辑弹窗、助手开关与上下文预算 |
| 成本看板 | `/billing` | 按助手会话汇总流水，按需展开原始明细 |

## 界面预览

### 创作助手与设置

![分镜工作区与创作助手](docs/images/screenshots/creation-agent.png)

对话与分镜并排查看，底部选择模型与引用对象，回复中的操作记录和用量支持折叠。

![创作助手通用配置](docs/images/screenshots/creation-agent-settings.png)

通用配置统一管理提示词语言、助手启用状态和运行限制。

### 其他页面

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

### LLM 大模型（实体提取 / 分镜 / 项目分析 / 重制拆解 / 创作助手）

采用 **OpenAI 兼容协议**，可接入 OpenAI、DeepSeek、豆包、月之暗面等。一个模型可同时勾选多个“能力用途”；只有支持视频输入的多模态模型才应勾选“重制”：

| 字段 | 说明 |
|------|------|
| 名称 | 配置显示名，如 `deepseek-v3` |
| API 地址 | 供应商 base_url，如 `https://api.deepseek.com/v1` |
| API Key | 你的密钥 |
| 模型名称 | 如 `deepseek-chat` |
| 接口协议 | `openai_compatible` |
| 支持 JSON 输出 | 分镜等结构化任务建议开启 |
| 能力用途 | 可多选内容理解、分镜规划、项目分析、重制、创作助手；“重制”要求模型支持视频输入 |
| 支持多轮工具调用 | 创作助手必需；仅开启支持 JSON 输出不能替代工具调用能力 |
| 上下文字符上限 / 最大输出 token | 模型级限制，与助手全局设置共同生效，填写供应商或代理实际支持的值 |
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

项目名按团队（无团队时按创建者）去重，不同范围允许同名。旧库的全局名称约束需人工审核后迁移，详见[项目命名与迁移说明](docs/project-name-scoping.md)。迁移默认只预览，不随启动自动执行。

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
uv run python -m scripts.backfill_media_derivatives
```

本地媒体会在原图旁生成 WebP 派生图；OSS 模式通过 `OSS_INTERNAL_ENDPOINT` 读写，并为派生图设置长期不可变缓存。该命令也会为设定资产图片生成缩略图，并为历史生成视频提取首帧海报。

### 视频任务自动收口

```dotenv
VIDEO_RECONCILE_INTERVAL_SECONDS=30
VIDEO_RECONCILE_BATCH_SIZE=50
```

后端会持续查询排队中和生成中的供应商任务。即使用户关闭故事版页面，任务完成、计费、尾帧提取与下一镜头注入仍会继续执行。

## Prompt 与规则定制（开发者）

新创作流程统一使用 **创作助手 + 一套中文 skills**。先启用助手并配置支持工具调用的模型，原有生成按钮和聊天入口共用相同能力。助手按系统语言输出，无需维护多语言生成规则。

生成效果需要调整时，修改 [`prompts/skills/`](prompts/skills/)：入口 `SKILL.md`；故事、资产、生图、分镜、重制、视频分别在 `story.md`、`assets.md`、`image.md`、`storyboard.md`、`remake.md`、`video.md`；共享风格和策略在 `styles.json`、`strategies.json`。

场景参考图的四格布局也在 `image.md`：默认采用铺满画面的 2×2 电影机位图，只有细分隔线，无视角标题、文字标注、白边或设计展示板。调整规则后，已有资产需要先用助手优化并保存提示词，再生成新图；直接点击重新生成仍会原样使用旧提示词。

分镜由 Agent 生成一份完整结构，再统一保存为包含禁止项、风格、引用、前置条件、动作和人声时间轴、转场及特效规范的 Prompt，避免另写摘要时漏掉对白或旁白。创作要求仍修改 `storyboard.md`，输出协议版本在 `storyboard_contract.json`；栏目序列化复用 `prompts/storyboard.py`，不包含另一套创作规则。视频提交原样使用已保存文本。旧任务与已保存分镜不自动改写，需重新生成才能应用新规则。

自由表述只提出候选操作；含糊请求需在页面核对对象并确认后才生成。重复提交使用数据库唯一回执，刷新后的未确认请求标识保存在浏览器本机。

任务提交时保存技能快照，规则修改仅影响新任务。已保存完整提示词默认原样使用；仅编辑提示词不会自动收费生成。旧中英文模板、归档目录和重复的规则翻译已删除，创作规则只维护 Skills。`prompts/locales/` 只保存显示及序列化标签。生图、分镜效果与共享风格都只改 Skills，新任务不组装旧模板，也不因助手失败回退旧流程。开发者修改规则、恢复与计费边界、测试方法详见 [统一技能开发指南](docs/agent-skills-workflow.md)。

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

## Star 增长

<!-- star-growth-card:start -->
<p align="center">
  <a href="https://github.com/Anning01/novelvids/stargazers">
    <img src="https://novelvids-star-history.864399407.workers.dev/card.svg" width="920" alt="猫影短剧 GitHub Star 增长曲线">
  </a>
</p>
<!-- star-growth-card:end -->

---

<p align="center">
  <sub>Built with passion by <a href="https://github.com/Anning01">Anning</a></sub>
</p>
