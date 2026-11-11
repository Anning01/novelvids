---
name: novelvids-video
description: 整理或修订逐镜视频生成请求、参考媒体、声音绑定与镜头衔接，处理成片和高清需求。
license: MIT
---

若本镜已交付故事版，用该生成段对应的一张线稿作为构图参考，按格内顺序衔接动作，配套 video_prompt 指定实际动作、运镜、声音与成片风格。

先整理镜头顺序、已确认的提示词、画幅、时长与参考素材。纯文字会话交付逐镜提交清单，标出未提供的媒体或模型能力；连接实际生成服务并获明确授权后才提交任务。

生成或修改视频提示词时，先完成通用稿，再按实际选中的视频模型执行专项优化。

- [模型专项提示词交付](references/model_optimization.md)
- [模型与专项技能映射](references/video_prompt_models.json)
- [选择专项技能](../scripts/select_video_optimizer.py)
- [视频制作规则](references/video.md)
- [风格要求](../novelvids-image/references/styles.json)
- [叙事与声音限制](../novelvids-storyboard/references/strategies.json)
- [单片段制作](references/clip_templates.json)
- [全片视听约定](../novelvids-storyboard/references/video_presentation.md)
