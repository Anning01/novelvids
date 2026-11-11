---
name: novelvids-storyboard
description: 将剧本或章节拆成分镜，或修改指定镜头的画面、运镜、时长、对白与转场。
license: MIT
---

读取导演剧本、场段资产与当前视频模型的可用时长，把连续表演编成尽量少的独立生成段。依据人物当下的处境和观众获知信息的时机，选择机位、画面、声音和节奏。每镜给出时长、出场对象、动作和人声时间轴；如要求完整视频提示词，按输出协议组装各栏。缺少素材 ID 时使用输入中的名字，不虚构平台记录。

开始时读取作品全局的「故事版」开关；开启后每个生成段交付一张黑白线稿故事版，画格随关键构图增减，配套视频提示词补齐动作、运镜、声音和成片风格。

生成或修改视频提示词时，先完成通用稿，再按实际选中的视频模型执行专项优化。

- [模型专项提示词交付](../novelvids-video/references/model_optimization.md)
- [模型与专项技能映射](../novelvids-video/references/video_prompt_models.json)
- [选择专项技能](../scripts/select_video_optimizer.py)
- [故事版开关与出图交付](references/storyboard_sheets.md)
- [线稿与视频配套提示词](references/storyboard_sheet_templates.json)
- [查询、切换和准备逐镜出图](../scripts/storyboard_sheets.py)
- [分镜写作](references/storyboard.md)
- [栏目与普通对白基准语速](references/storyboard_contract.json)
- [叙事策略](references/strategies.json)
- [画面风格](../novelvids-image/references/styles.json)
- [跨镜资产形态与引用](../novelvids-assets/references/asset_lifecycle.md)
- [首次出场与分镜修订](references/storyboard_templates.json)
- [人物语速与表演](references/speech_pacing.md)
- [全片视听约定](references/video_presentation.md)
- [内部切镜的空间定位图](references/blocking.md)
- [定位线稿绘制工具](../scripts/draw_blocking.py)
