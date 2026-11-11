---
name: novelvids-remake
description: 依据参考视频与原声提取视觉资产、切镜、动作和对白，或按指定时间段校正拆解稿。
license: MIT
---

先核实能实际读取的画面和音轨范围，再按来源时间整理资产与镜头。只有截图或转录时标明缺失证据；只对可读的内容作判断。按用户要求交付资产表或逐镜制作资料。

- [视频拆解规则](references/remake.md)
- [视觉资产提取](../novelvids-assets/references/assets.md)
- [图像版式](../novelvids-image/references/image.md)
- [资产协议](../novelvids-assets/references/asset_contract.json)
- [分镜规则](../novelvids-storyboard/references/storyboard.md)
- [分镜协议](../novelvids-storyboard/references/storyboard_contract.json)
- [风格](../novelvids-image/references/styles.json)
- [策略](../novelvids-storyboard/references/strategies.json)
- [资产形态](../novelvids-assets/references/asset_lifecycle.md)
- [资产清点、定点补漏与修订](../novelvids-assets/references/asset_templates.json)
- [首次出场与分镜修订](../novelvids-storyboard/references/storyboard_templates.json)
- [按阶段提取资产与镜头](references/remake_templates.json)
- [人声时间窗与跨镜语速](../novelvids-storyboard/references/speech_pacing.md)
- [独立语速检测脚本](../scripts/check_speech.py)

审稿前运行 `python3 scripts/check_speech.py 分镜.json`（从导出的技能目录执行）。输入为按播放顺序排列的 `shots`，每镜含 sequence、duration、dialogue 和 narration；可附 entities 的人物登记名与别名。时间轴格式见人声规范。
