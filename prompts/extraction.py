"""场景/人/物提取 prompt"""

PERSON_SYSTEM_PROMPT = """You are an expert at analyzing novel text and extracting character information.
Your task is to identify all persons/characters mentioned in the text and extract their details.

For each character, extract:
1. Name (the most commonly used name)
2. Aliases (other names, nicknames, titles used to refer to them)
3. Description (Chinese description of the character)
4. Base traits (stable visual identity only, written in {prompt_language_name})
5. Reference layout (character_turnaround for one human/animal; group_portrait for a recurring group)
6. Appearances (where in the text they appear)

Output in JSON format."""

PERSON_EXTRACTION_PROMPT = """分析以下第 {chapter_number} 章的文本，提取所有出现的人物角色。

文本内容：
---
{text}
---

请以 JSON 格式输出，格式如下：
```json
{{
  "persons": [
    {{
      "name": "标准名称",
      "aliases": ["别名1", "别名2"],
      "description": "中文描述：性格、身份、背景等",
      "base_traits": "使用{prompt_language_name}撰写的详细视觉描述，用于AI图像生成",
      "reference_layout": "character_turnaround 或 group_portrait",
      "appearances": [
        {{"line": 10, "context": "张三走进房间..."}}
      ]
    }}
  ]
}}
```

base_traits 只写资产自身稳定的视觉内容，不写三视图、画幅、镜头构图、当前动作、临时表情或剧情事件，固定版式由程序补齐。

单个人类或动物必须使用 character_turnaround，并按以下14项顺序完整输出；内容使用{prompt_language_name}，无法确认仍保留字段并填“无/None”：
时代基底、国家/朝代、人种（动物写物种和品种）、类型基底、脸型、发型（动物写毛发/羽毛/鳞片）、耳饰、身材、头身比、上身着装、下身着装、鞋子（动物写爪/蹄/足部）、性别、年龄。
每项只写跨镜头稳定可见的体貌和装束；服装写清颜色、材质、结构、纹样、磨损和层次。

多人或动物群体必须使用 group_portrait，并按以下15项顺序完整输出；内容使用{prompt_language_name}：
人物特征、年龄段、性别、种族、人数规模、身材、脸型、眉毛、眼镜、鼻子、嘴唇、皮肤、特殊标记、发型、服饰和道具。
每项先写群体共性，再写合理个体差异；不写队列、冲锋、行走等当前动作。

注意：
1. 同一个人物可能有多个称呼，需要识别并合并
2. base_traits 必须使用{prompt_language_name}，要足够详细以生成准确的角色形象
3. 只提取明确出现在文本中的人物
4. description 只写人物在剧情中的身份、性格和背景，不得混入 base_traits
5. 不提取一次性路人或一次性群像"""

SCENE_SYSTEM_PROMPT = """You are an expert at analyzing novel text and extracting scene/location information.
Your task is to identify all scenes, locations, and environments mentioned in the text.

For each scene, extract:
1. Name (the location/scene name)
2. Description (Chinese description)
3. Base traits (DETAILED visual traits in {prompt_language_name} for AI image generation - must include: architectural style, spatial features, lighting/atmosphere, and key visual elements)
4. Appearances (where in the text it appears)

Output in JSON format."""

SCENE_EXTRACTION_PROMPT = """分析以下第 {chapter_number} 章的文本，提取所有出现的场景/地点。

文本内容：
---
{text}
---

请以 JSON 格式输出，格式如下：
```json
{{
  "scenes": [
    {{
      "name": "场景名称",
      "aliases": ["别名"],
      "description": "中文描述：环境、氛围、特点等",
      "base_traits": "使用{prompt_language_name}撰写的详细视觉描述，用于AI图像生成",
      "appearances": [
        {{"line": 5, "context": "他来到皇宫大殿..."}}
      ]
    }}
  ]
}}
```

base_traits 必须使用{prompt_language_name}写成一段连续、可从不同视角重建同一空间的场景设定，严格包含：
1. 横向长幅全景、真实比例和水平平面投影；直线、地平线和垂直物体保持笔直，排除鱼眼、球面、桶形和小行星畸变。
2. 场景名称、时代风格、室内/室外、整体规模、空间外形、主要延伸方向或中轴线。
3. 按近景、中景、远景描述地面、建筑、地形和固定陈设，写明左、右、中央、前、后、上、下及相对关系。
4. 成组、重复、对称或沿路径排列的元素需写清数量、间距、排列方向和覆盖范围。
5. 机位、观察方向、地平线高度、稳定光源、天气和主色调。
只描述固定空间，不出现人物、动物、临时道具、动作、战斗、技能或特效；不要使用“旁边、附近、若干”等无法重建空间的模糊表达。

注意：
1. 场景包括：建筑、房间、自然环境、城市、地点等
2. base_traits 必须使用{prompt_language_name}，要足够详细以生成准确的场景画面
3. 只提取明确出现在文本中的场景
4. 相同场景的不同角度、景别和局部区域必须合并
5. description 只写剧情语义，不得代替 base_traits"""

ITEM_SYSTEM_PROMPT = """You are an expert at analyzing novel text and extracting important item/object information.
Your task is to identify all significant items, weapons, artifacts, and objects mentioned in the text.

For each item, extract:
1. Name (the item name)
2. Description (Chinese description)
3. Base traits (DETAILED visual traits in {prompt_language_name} for AI image generation - must include: material/texture, shape/form, color/finish, and distinctive features)
4. Appearances (where in the text it appears)

Output in JSON format."""

ITEM_EXTRACTION_PROMPT = """分析以下第 {chapter_number} 章的文本，提取所有重要的物品/道具。

文本内容：
---
{text}
---

请以 JSON 格式输出，格式如下：
```json
{{
  "items": [
    {{
      "name": "物品名称",
      "aliases": ["别名"],
      "description": "中文描述：外观、功能、来源等",
      "base_traits": "使用{prompt_language_name}撰写的详细视觉描述，用于AI图像生成",
      "appearances": [
        {{"line": 20, "context": "他拔出神剑..."}}
      ]
    }}
  ]
}}
```

base_traits 必须使用{prompt_language_name}写成一段连贯的道具视觉设定，写清品类、整体轮廓与比例、材质、颜色、结构部件、纹样或准确可见文字、表面质感、磨损和独有识别特征。
只写跨镜头稳定可见、需要保持同一造型的内容；同一产品的不同角度、开合状态和轻微文字识别差异必须合并。

注意：
1. 只提取重要的物品（武器、法宝、信物、关键道具等）
2. 不要提取普通的日常物品（除非在剧情中很重要）
3. base_traits 必须使用{prompt_language_name}，要足够详细以生成准确的物品图像
4. 相同物品的不同称呼需要合并
5. description 只写剧情功能或来源，不得混入 base_traits"""
