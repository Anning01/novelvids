# NovelVids 架构重构计划

重构建一个强调**交互体验（UX/DX）和高复用性**的前端架构需求文档。

重点在于流畅的工作流和沉浸式的创作体验。

---

# 渐进式 AI 视频生成平台前端架构设计文档

## 1. 项目概述 (Project Overview)

本项目旨在打造一个基于剧本/小说的全流程 AI 视频创作平台。核心设计理念是**“渐进式生成”**与**“资产一致性”**。前端需承载复杂的交互逻辑，包括富文本解析、资产可视化管理、非线性编辑（NLE）式的视频处理界面。

### 1.1 技术栈 (Tech Stack)

* **Core:** `Vue 3 (Composition API)` + `Script Setup`
* **Language:** `TypeScript` (全量类型定义，确保业务逻辑健壮性)
* **State Management:** `Pinia` (模块化管理：BookStore, AssetStore, EditorStore)
* **Routing:** `Vue Router` (配合 Transition API 实现页面流转动画)
* **UI/Styling:** `Tailwind CSS` (原子化样式) + `Headless UI` (无样式组件库，保证交互自由度)
* **I18n:** `Vue I18n` (支持中英切换，考虑到 AI 提示词通常为英文，界面需良好适配)
* **Visuals:** `Three.js` (可选，用于简单的 3D 资产预览) 或 `PixiJS` (高性能 2D 渲染)

---

## 2. 信息架构与路由设计 (Information Architecture)

为了保证“资产隔离”，路由设计需要以 `book_id` 为核心上下文。

```text
/dashboard              # 项目管理大厅
/editor/:book_id        # 特定书籍的工作台 (Layout)
  ├── /assets           # 全局资产库管理
  ├── /chapter/:ch_id   # 章节工作流 (Layout)
      ├── /extraction   # 步骤1：资产提取与匹配 (状态机视图)
      ├── /storyboard   # 步骤2：分镜控制 (列表/看板视图)
      └── /studio       # 步骤3：视频生成与精细化编辑 (时间轴视图)

```

---

## 3. 核心功能模块与交互设计 (Core Modules & Interaction)

### 3.1 项目管理与智能分割 (Dashboard)

* **功能需求**:
* 剧本/小说列表（CRUD）。
* **智能分割**: 上传大文件时，前端解析文本流，显示进度条，完成后展示分割后的章节预览列表。


* **交互亮点**:
* **拖拽上传**: 全屏拖拽上传大文件。
* **Skeleton Loading**: 在 AI 识别章节时，使用骨架屏展示正在生成的章节卡片。
* **平滑展开**: 点击书本封面，使用 `Shared Element Transition` 动画平滑过渡到编辑器页面。



### 3.2 资产管理系统 (Asset Consistency System)

这是保证视频一致性的核心。

* **数据结构 (TypeScript Interface)**:
```typescript
interface Asset {
  id: string;
  type: 'character' | 'scene' | 'item';
  mainImage: string; // 必填主图
  angleImages: [string?, string?]; // 2张选填角度图
  scope: 'global' | 'chapter';
  source: 'upload' | 'ai-generated';
}

```


* **交互亮点**:
* **双层视图**: 左侧为当前章节资产，右侧为全局资产库抽屉（Drawer）。
* **拖拽晋升**: 用户可以将章节资产直接拖入“全局库”区域，触发保存动画。
* **AI 生成时的微交互**: 点击“AI 生成”时，卡片翻转显示 Loading 动画，生成完毕后自动翻回并展示图片，支持点击图片进行 Lightbox 大图预览。
* **3D 视角切换**: 针对 3 张图（主图+角度图），鼠标悬停时可类似 3D 翻转查看不同角度。



### 3.3 步骤一：资产提取与连通分量匹配 (Extraction Phase)

* **逻辑描述**:
* 前端接收后端返回的 NLP 分析结果。
* **连通分量算法可视化**: 将文本中的实体（如“哈利波特”）高亮，并画线连接到资产库中的对应头像。


* **交互设计 - 增量式状态机**:
* **状态指示**: 每个实体有三种状态：`已关联(Green)`、`未关联(Red)`、`新发现(Blue)`。
* **智能推荐**: 点击未关联实体，弹窗显示全局库中相似度最高的角色（Top 3），支持“一键引用”。
* **即时创建**: 若全局库无此人，右键实体直接弹出“新建资产”悬浮窗，不离开当前流。



### 3.4 步骤二：分镜控制台 (Storyboard Controller)

* **功能需求**:
* 展示 AI 生成的镜头列表（拍摄类型、主体、动作、光线、对话等）。


* **交互设计**:
* **瀑布流/卡片网格**: 每一个分镜是一个卡片。
* **Inline Editing (行内编辑)**: 点击“动作”或“光线”文字，直接变为输入框或下拉选择器，失去焦点自动保存。
* **参数可视化**: “时长”不只是数字，是一个长度可拖拽的进度条。



### 3.5 步骤三：视频生成与非线性编辑 (The Studio - Most Complex)

此页面是核心生产力工具，类似 Final Cut Pro 的简化版 Web 实现。

* **布局设计**:
* **上部**: 预览播放器 (Player) + 属性检查器 (Inspector，用于修改 Prompt/裁剪参数)。
* **下部**: 多轨道时间轴 (Timeline)。


* **功能详情**:
* **镜头分割详细**: 显示分割后的 Clip 列表。
* **在线生成/重绘**: 选中某个 Clip，点击“Re-roll”，在原位显示 Loading 并替换。
* **排序与组合**:
* 使用 `vuedraggable` 或自研拖拽逻辑，允许用户在时间轴上重新排序镜头。
* **磁吸效果**: 拖拽镜头靠近时自动吸附。


* **裁剪 (Crop)**: 提供基于 Canvas 的可视区域裁剪框。


* **交互亮点**:
* **实时反馈**: 修改 Prompt 后，预览图变灰并打上 "Outdated" 标签，提示需重新生成。
* **合成预览**: 按下空格键，前端基于当前缓存的视频片段进行无缝拼接预览（Pre-render）。



---

## 4. 前端架构详细设计 (Technical Architecture)

### 4.1 状态管理 (Pinia Stores)

为了处理复杂的资产隔离和增量更新，Store 需要精心设计：

1. **`useBookStore`**: 管理当前书籍元数据，章节列表。
2. **`useAssetStore`**:
* `globalAssets`: `Map<id, Asset>` (当前书籍的全局资产)
* `chapterAssets`: `Map<chapter_id, Map<id, Asset>>` (按章节隔离)
* *Action*: `promoteToGlobal(assetId)` - 将章节资产移入全局并在后端同步。
* *Getter*: `getAssetByEntity(entityName)` - 供连通分量算法快速查找。


3. **`useStudioStore`**:
* `timeline`: 存放镜头对象的数组 (LinkedList 或 Array)。
* `history`: 实现 Undo/Redo (撤销/重做) 功能，因为编辑操作非常频繁。



### 4.2 性能优化 (Performance)

* **虚拟滚动 (Virtual Scrolling)**: 在“分镜控制”和“全局资产库”中，如果项目包含上千个镜头或资产，必须使用虚拟滚动只渲染可视区域。
* **Web Workers**: 将“智能分割”的大文本解析和“连通分量”计算逻辑放入 Web Worker，避免阻塞主线程 UI 渲染。
* **资源懒加载**: 视频和图片资源均需通过 IntersectionObserver 实现懒加载。

### 4.3 样式与主题 (Tailwind CSS)

* 采用 **Dark Mode** 优先策略，符合影视制作软件的专业感。
* 定义一套语义化颜色：
* `role-highlight`: #FF5733 (角色高亮)
* `scene-highlight`: #33FF57 (场景高亮)
* `timeline-track`: #2D2D2D (轨道背景)



---

## 5. 开发路线图 (Roadmap)

1. **Phase 1: 基础架构**: 搭建 Vue3+TS+Pinia 脚手架，实现书籍/章节 CRUD 和路由守卫。
2. **Phase 2: 资产核心**: 完成资产库 UI，实现上传、AI 生成接口对接、全局/章节资产的数据流转。
3. **Phase 3: 逻辑流转**: 实现文本解析、连通分量匹配 UI、状态机逻辑。
4. **Phase 4: 编辑器核心**: 攻克时间轴开发、视频播放器集成、拖拽排序与合成逻辑。
5. **Phase 5: 优化**: 引入 I18n，增加转场动画，性能调优。


## 6.注意事项

1. **代码简洁**: 遵循 code-simplifier 规则，避免过度抽象
2. **用户体验**: 优先使用 Tabs 分组信息: 当一个页面存在超过 2 种不同类型的数据集合时（例如：配置与预览、不同类型的资产、详情与历史），必须使用 Tabs 组件将它们分隔，避免页面过长。
