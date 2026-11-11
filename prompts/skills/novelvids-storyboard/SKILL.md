---
name: novelvids-storyboard
description: 将剧本或章节拆成分镜，或修改指定镜头的画面、运镜、时长、对白与转场。
license: MIT
---

输入正文、可引用资产和目标镜头时长，按剧情顺序交付镜头。每镜给出时长、出场对象、动作和人声时间轴；如要求完整视频提示词，按输出协议组装各栏。缺少素材 ID 时使用输入中的名字，不虚构平台记录。

- [分镜写作](references/storyboard.md)
- [栏目和人声时长预算](references/storyboard_contract.json)
- [叙事策略](references/strategies.json)
- [画面风格](../novelvids-image/references/styles.json)
- [跨镜资产形态与引用](../novelvids-assets/references/asset_lifecycle.md)
- [首次出场与分镜修订](references/storyboard_templates.json)
- [人声时间窗与跨镜语速](references/speech_pacing.md)
- [独立语速检测脚本](../scripts/check_speech.py)

审稿前运行 `python3 scripts/check_speech.py 分镜.json`（从导出的技能目录执行）。输入为按播放顺序排列的 `shots`，每镜含 sequence、duration、dialogue 和 narration；可附 entities 的人物登记名与别名。时间轴格式见人声规范。
