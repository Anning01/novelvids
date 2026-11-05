# 公开版与自用版提示词

两版共用业务代码、接口与模型调用链。公开资源正常提交到仓库，自用资源以 `.anning` 为后缀放在同目录，Git 默认忽略。加载器按文件选择自用覆盖；未提供覆盖的部分继续使用公开资源。

| 内容 | 公开文件 | 自用覆盖 |
|---|---|---|
| 创作助手基础规则 | `prompts/skills/SKILL.md` | `prompts/skills/SKILL.anning.md` |
| 资产提取提示词 | `prompts/skills/assets.md` | `prompts/skills/assets.anning.md` |
| 图片提示词 | `prompts/skills/image.md` | `prompts/skills/image.anning.md` |
| 分镜提示词 | `prompts/skills/storyboard.md` | `prompts/skills/storyboard.anning.md` |
| 风格提示词 | `prompts/skills/styles.json` | `prompts/skills/styles.anning.json` |
| 叙事策略规则 | `prompts/skills/strategies.json` | `prompts/skills/strategies.anning.json` |
| 资产输出格式 | `prompts/skills/asset_contract.json` | `prompts/skills/asset_contract.anning.json` |

`story`、`remake`、`video`、`editing` 等其余已登记资源遵循同一命名方式。`prompts/*.py` 保留为共享渲染代码，不复制两套业务逻辑。`prompts/locales` 的界面及协议标签保持共享。

## 覆盖规则

- Markdown 文件整份替换，不自动拼接。先复制公开文件再改，避免遗漏仍需要的指令；自用 Markdown 为空时直接报错。
- JSON 文件按第一层键合并。同名键的整个值由自用版替换，公开版其他键保留；不递归合并。`styles` 的每个风格必须同时提供 `label`、`image`、`video`。
- `asset_contract.json` 的公开默认值为 `{}`，保持公开版现有输出行为。自用版可以按 `zh`、`en` 提供完整的各类型任务、标题、字段和末尾禁止项；修改某一语言时需保留该语言下全部资产类型。
- 自用文件格式错误直接报错，不悄悄回退到公开版。不要把密钥或个人数据写入提示词资源。

## 本地与部署

只部署 Git 仓库就是公开版。自用部署在相同代码之上，额外复制所需的 `.anning.md`、`.anning.json` 文件到对应路径。发布包不要从整个脏工作区打包；公开包必须从 Git 提交构建，确保不包含自用文件。

自用资源应单独备份或保存在私有内容仓库。它们不在 `git archive` 的代码备份中；自用部署需独立备份、传输与回滚，不能只备份代码。当前改动不自动上传自用文件。

更换内容后重启后端，使启动时读取的风格及叙事配置也刷新。新任务将实际生效内容保存到运行快照，内容变化会改变 revision；历史任务继续使用原有快照，不被后来修改的文件改变。数据库中已经保存的资产提示词和项目自定义风格不自动重写。
