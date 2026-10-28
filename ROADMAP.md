# 创作体验路线图 / Creative workflow roadmap

[中文 README](README.md) · [English README](README.en.md) · [Issues](https://github.com/Anning01/novelvids/issues)

这里按创作体验组织后续讨论，不承诺版本、时间或模型效果。功能是否已经实现，以当前代码和指南为准；具体需求、复现样例与实施范围在 Issues 中讨论。

These are directions for discussion, not release dates, delivery commitments or guarantees of model output. The code and guides describe current behavior; use issues to define concrete work.

| 方向 / Direction | 当前基础 / Existing foundation | 欢迎讨论 / Open questions |
| --- | --- | --- |
| 角色与场景一致性 / Asset consistency | 项目资产、别名、形态、图片版本与声音绑定 / Assets, aliases, variants, image history and voice bindings | 更清晰的跨章节身份检查，模型间效果样例 / Cross-chapter identity checks and comparable model examples |
| 可复现、可调整的工作流 / Reproducible workflows | 保存完整 Prompt、技能与语言快照、任务及回执 / Saved prompts, skill/language snapshots, tasks and receipts | 如何让创作者更容易定位效果变化、控制批量部分失败 / Explain output changes and manage partial batch failures |
| 部署与恢复体验 / Deployment and recovery | Docker 编排、持久化数据、后台收集与恢复 / Compose, persistent data, background collection and recovery | 简化首次配置、改善安装前置项与失败定位 / Easier onboarding, runtime prerequisites and diagnostics |
| 模型与 Skills 扩展 / Extensibility | 配置驱动的能力适配、一套中文创作规则 / Configured capability adapters and one Chinese skill pack | 社区贡献的模型合同与可复用技能样例 / Community model contracts and reusable skill examples |
| 成片质量检查 / Production quality | 视频版本、尾帧连续性、章节合并与画质增强 / Versions, last-frame continuity, composition and enhancement | 对白、声音、引用及镜头连续性的检查体验 / Review dialogue, voices, references and continuity |

想推动其中一项，请提供一个可公开的故事/镜头样例、遇到的问题和希望改善的具体步骤；涉及真实生成时，注明模型及愿意使用的测试预算。

To move an idea forward, share an authorized story/shot example, the problem and the steps you want to improve. For live generation, identify the model and test budget.
