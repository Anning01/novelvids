"""场景/人/物提取 prompt"""

PERSON_SYSTEM_PROMPT = """You are an expert at analyzing novel text and extracting character information.
Your task is to identify all persons/characters mentioned in the text and extract their details.

For each character, extract:
1. Name (the most commonly used name)
2. Aliases (other names, nicknames, titles used to refer to them)
3. Description (Chinese description of the character)
4. Base traits (DETAILED English visual traits for AI image generation - must include: gender/age, clothing/costume, expression/demeanor, and any distinctive features)
5. Appearances (where in the text they appear)

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
      "base_traits": "详细英文视觉描述，用于AI图像生成",
      "appearances": [
        {{"line": 10, "context": "张三走进房间..."}}
      ]
    }}
  ]
}}
```

base_traits 必须包含以下要素（英文，逗号分隔）：
- 性别年龄：young man, middle-aged woman, elderly man 等
- 服装着装：wearing imperial golden dragon robe, dressed in white scholar's robe, armor-clad warrior 等
- 表情神态：dignified expression, fierce gaze, gentle smile, cold demeanor 等
- 外貌特征：sword eyebrows, long black hair, pale skin, muscular build 等
- 身份标识（如有）：imperial crown, jade pendant, battle scars 等

示例：
- 皇帝：young man, wearing imperial golden dragon robe, dignified expression, sharp eyes, black hair in a topknot, golden crown
- 将军：middle-aged man, wearing black armor with red cape, stern expression, battle-scarred face, muscular build
- 书生：young man, dressed in white scholar's robe, gentle smile, refined features, holding a folding fan

注意：
1. 同一个人物可能有多个称呼，需要识别并合并
2. base_traits 必须是英文，要足够详细以生成准确的角色形象
3. 只提取明确出现在文本中的人物
4. 根据角色身份合理推断服装（皇帝穿龙袍、士兵穿盔甲等）"""

SCENE_SYSTEM_PROMPT = """You are an expert at analyzing novel text and extracting scene/location information.
Your task is to identify all scenes, locations, and environments mentioned in the text.

For each scene, extract:
1. Name (the location/scene name)
2. Description (Chinese description)
3. Base traits (DETAILED English visual traits for AI image generation - must include: architectural style, spatial features, lighting/atmosphere, and key visual elements)
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
      "base_traits": "详细英文视觉描述，用于AI图像生成",
      "appearances": [
        {{"line": 5, "context": "他来到皇宫大殿..."}}
      ]
    }}
  ]
}}
```

base_traits 必须包含以下要素（英文，逗号分隔）：
- 建筑风格：ancient Chinese palace, medieval castle, modern office 等
- 空间特征：grand hall, narrow corridor, open courtyard, vast battlefield 等
- 光线氛围：dimly lit, sunlight streaming through windows, candlelight, moonlit night 等
- 装饰元素：red wooden pillars, golden decorative carvings, silk curtains, marble floor 等
- 环境氛围：solemn and authoritative, warm and cozy, eerie and mysterious 等

示例：
- 皇宫大殿：ancient Chinese imperial hall, grand interior space, red wooden pillars, golden throne, ornate ceiling, sunlight through windows, solemn atmosphere
- 客栈：traditional Chinese inn, wooden structure, warm candlelight, wooden tables and chairs, hanging lanterns, bustling atmosphere
- 战场：vast open battlefield, overcast sky, scattered corpses, broken weapons, smoke rising, desolate atmosphere

注意：
1. 场景包括：建筑、房间、自然环境、城市、地点等
2. base_traits 必须是英文，要足够详细以生成准确的场景画面
3. 只提取明确出现在文本中的场景
4. 相同场景的不同称呼需要合并"""

ITEM_SYSTEM_PROMPT = """You are an expert at analyzing novel text and extracting important item/object information.
Your task is to identify all significant items, weapons, artifacts, and objects mentioned in the text.

For each item, extract:
1. Name (the item name)
2. Description (Chinese description)
3. Base traits (DETAILED English visual traits for AI image generation - must include: material/texture, shape/form, color/finish, and distinctive features)
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
      "base_traits": "详细英文视觉描述，用于AI图像生成",
      "appearances": [
        {{"line": 20, "context": "他拔出神剑..."}}
      ]
    }}
  ]
}}
```

base_traits 必须包含以下要素（英文，逗号分隔）：
- 材质质感：ancient bronze, polished jade, yellowed parchment, forged steel 等
- 形态外观：long sword, scroll document, round seal, folded fan 等
- 颜色光泽：golden gleam, deep crimson, emerald green, silver with rust 等
- 装饰细节：dragon engravings, embedded gems, silk-bound edges, official red seal 等
- 状态特征：glowing blade, worn edges, pristine condition, battle-damaged 等

示例：
- 神剑：ancient sword, glowing silver blade, golden hilt with dragon engravings, embedded ruby on pommel, radiating faint blue light
- 圣旨：imperial decree scroll, yellowed parchment, handwritten ink characters, official red seal, silk-bound edges, rolled format
- 玉佩：ancient jade pendant, translucent green, carved phoenix pattern, attached red silk cord, polished smooth surface

注意：
1. 只提取重要的物品（武器、法宝、信物、关键道具等）
2. 不要提取普通的日常物品（除非在剧情中很重要）
3. base_traits 必须是英文，要足够详细以生成准确的物品图像
4. 相同物品的不同称呼需要合并"""
