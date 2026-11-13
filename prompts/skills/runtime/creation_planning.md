# 制定可执行创作方案
依据用户要求、已完整阅读的章节证据和现有对象制定方案。summary 简短说明具体创作决定、来源和编排。
步骤只使用 brief.operations；必要的缺失文字资产可用 assets 作为分镜的依赖，但不能自动加图片或视频。沿用已有设定，不修改原著正文。
storyboard 的一个步骤就是整章生成请求，同一章节只能有一个 storyboard 步骤。开场、倒叙、回到现实、转折、结尾属于该步骤 instructions 内的叙事段落，不能拆成针对同一章的多个生成步骤。
每步指定一个实际 target_id（assets/storyboard 为章节，image 为基础资产，可带 variant_id，video 为分镜）；也可用 source_step 引用已列出的 assets 步骤产出的资产来生图，或 storyboard 步骤产出的分镜来生成视频，不猜未来 ID。依赖必须在前。
mode 默认 fill_missing，保留已有成果。仅新要求明确需要修改既有内容时用 revise 并在 label 和 summary 明示。分镜 revise 表示整章重做，不能隐瞒。image/video 的 revise 必须包含提示词调整意图。
用户明确要求图片或视频重新生成、但不修改提示词时，使用 regenerate；此模式沿用已有提示词重新调用媒体模型，不自动改写已确认设计。普通批量生成仍默认 fill_missing。
每步 requirement_ids 仅列适用要求。sources 从阅读候选中选准确的原文范围；跨章编排必须携带选段。instructions 写明确创作方案，包括顺序、切换、衔接及验收要求，不只是重复用户原话。例如倒叙需要明确选中的事件、保留的悬念及切回点，但不要因示例而擅自采用倒叙。
选取阅读候选时只复制其 chapter_id 和 reference_id；start/end 及原文由服务器解析，不抄写 quote，不计算字符位置。引用编号只能来自给出的已读候选。
asset_ids 只使用实际需要出镜的目录资产。缺失文字资产应先提取来源章资产，再由后续步骤读取结果，不更改资产原始章节归属。不得跨越 brief.write_chapter_ids；参考章节不是可写范围。
assets 还可使用 brief.asset_chapter_ids 中明确要求提取资产的来源章，保持原文不变；这不允许对该章增加 storyboard 步骤。资产内容和分镜内容由对应结构化生成步骤完成，方案只携带来源编号、要求和依赖，不在方案 JSON 中嵌入完整提示词。
仅作为分镜前置依赖的缺失文字资产允许从已阅读的来源章提取，并在 label 和 summary 明示。除此之外不修改参考章节。brief.operations 中要求生成的每个写入章节都必须有对应步骤，不能只做第一章便宣称全书完成。
variant_ids 用于明确选择出镜资产的已有形态，每个基础资产最多一个；仅使用目录 ID。image 的 variant_id 是本次生图目标，不能混淆两者。
