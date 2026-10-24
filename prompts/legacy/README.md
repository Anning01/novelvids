# 历史兼容资源（冻结）

这里归档 Skills 迁移前的中英文模板，内容原样保留，不再同步创作规则或新增语言版本。**调整生成效果只修改 `prompts/skills/`。**

- 无 `workflow_version=agent-skills-v1` 标记的历史任务仍可使用这些模板恢复；旧结构化提示词的解析与确定性渲染也保留。
- 新任务的创作指令、风格与策略来自提交时保存的 Skills 快照；不读取这里的模板、不在助手失败时回退到这里。
- `prompts/locales/` 只保存双语显示与序列化标签；前端界面词典继续独立翻译。它们不是第二套创作规则。
- 本次只移动文件和调整读取位置，没有修改数据库或旧模板正文。回滚代码即可恢复原读取位置，历史数据无需迁移。
- 此目录仅允许修复历史兼容问题，不作为生成质量调优入口。回归会校验归档内容未变，以及新创作任务不读取本目录。

English: These bilingual resources are frozen for historical tasks and deterministic rendering of older documents. Maintain creative rules only in `prompts/skills/`. New tasks use skill snapshots without falling back here. This relocation requires no data migration.
