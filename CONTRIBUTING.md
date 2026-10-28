# 参与 NovelVids / Contributing

[中文 README](README.md) · [English README](README.en.md) · [路线图 / Roadmap](ROADMAP.md)

欢迎提交可复现的创作问题、文档修正、Skills 改进和代码贡献。先从一个明确的问题开始，避免把模型效果、界面、权限和计费变化混在同一个大改动里。

We welcome reproducible creative-workflow bugs, documentation fixes, skill improvements and code contributions. Start with one concrete problem and keep the change reviewable.

## 报告问题 / Report a problem

在 [Issues](https://github.com/Anning01/novelvids/issues) 搜索已有讨论。新问题尽量包含：

- 使用版本、操作系统、Docker 或本地运行方式。
- 复现步骤、期望结果和实际结果；界面问题注明语言、主题和屏幕宽度。
- 生成问题提供可公开的最小文本、模型能力类型、参考素材是否使用、保存提示词与实际结果。
- 脱敏错误信息和任务状态；不要粘贴 Key、令牌、签名 URL、完整数据库或私人书稿。

Search existing [issues](https://github.com/Anning01/novelvids/issues) before opening one. Include the version, environment, reproduction steps, expected/actual behavior, language/theme for UI bugs, and a shareable minimal input for generation issues. Redact credentials, signed URLs and private content.

## 选择贡献入口 / Find an entry point

| 方向 / Area | 从这里开始 / Start here |
| --- | --- |
| 改善生图、分镜、角色提取 / Generation quality | [`prompts/skills/`](prompts/skills/) · [中文指南](docs/agent-skills-workflow.md) · [English guide](docs/agent-skills-workflow.en.md) |
| 接入图片、视频模型 / Model adapters | [`services/image_generation/`](services/image_generation/) · [`services/video/`](services/video/) |
| 画布与故事板 / Canvas and storyboard | [`web/src/features/workbench/`](web/src/features/workbench/) · [`web/src/pages/`](web/src/pages/) |
| 语言与文档 / Localization and docs | [`web/src/i18n/`](web/src/i18n/) · [中文文档](README.md#文档中心) · [English docs](README.en.md#documentation) |
| 任务与费用 / Tasks and usage | [`services/creation_agent/`](services/creation_agent/) · [`services/billing/`](services/billing/) |

较大的接口、数据库、权限、计费或依赖改动，请先在 Issue 中说明问题、方案与兼容影响。欢迎先提交失败回归或小样例，帮助定位根因。

For larger API, schema, permission, billing or dependency changes, discuss the problem, approach and compatibility impact in an issue first. A failing regression or minimal example is a useful first contribution.

## 开发与检查 / Develop and verify

环境搭建见[开发指南](docs/development.md) / [development guide](docs/development.en.md)。仓库约束见 [AGENTS.md](AGENTS.md)。

- 常规功能分支基于 `develop`；PR 目标也使用 `develop`，除非维护者另有说明。
- 提交信息使用 `type(scope): description`，例如 `fix(workbench): preserve selected video`。
- 先运行相关回归。前端改动还需 `npm run typecheck`、`npm run build` 和 dark/light 检查。
- 权限测试以 `AUTH_ENABLED=true` 单独运行；普通后端回归使用 `AUTH_ENABLED=false`。
- 真实模型调用需明确的配置和费用预算。请区分模拟验证、真实效果验证和未执行的验收。
- 提交前运行 `git diff --check`，不提交密钥、数据库、媒体、构建产物或依赖目录。
- Skills 修改说明使用的最小输入、修改前后差异与语言；不要另建一套中英文创作规则。

Branch from `develop` and target `develop` in pull requests unless directed otherwise. Use conventional commit messages. Run focused regressions, plus frontend typecheck/build and dark/light checks when applicable. Run authentication tests separately. Live model tests need an explicit budget and configuration. Never commit secrets, databases, generated media, build outputs or dependency directories.

A useful PR description states the original problem, resulting behavior, validation performed and remaining limits. Do not report mocked provider output as real generation acceptance.

## 许可与来源 / Licensing and attribution

你的贡献应当是你有权提交、并可按本项目 [MIT License](LICENSE) 发布的内容。引入第三方代码或素材时说明来源并保留其许可；不要移除现有 [第三方声明](NOTICE.md)。这不要求你转让版权，也不代表模型、字体或示例作品的权利统一改变。

Submit work you have the right to contribute under the project's [MIT License](LICENSE). Identify and preserve any third-party licenses and provenance. See [NOTICE.md](NOTICE.md). Contributing does not transfer your copyright or relicense third-party models, fonts or media.
