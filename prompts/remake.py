"""重制工坊视频拆解 Prompt 与严格 JSON 契约。

内容同步自 shengshimedia 无限画布复刻流水线；本模块保持无副作用，业务调用、
媒体加载、计费和持久化由 services/remake 负责。
"""

from typing import Any


SINGLE_CHARACTER_PROMPT_PREFIX = """任务：完成角色的上半身正面平视特写和该角色的全身三视图，左边是角色的上半身正面平视特写，右边是该角色的全身三视图。中性浅灰白色、无缝摄影棚背景、无环境元素、无墙角和地平线、仅保留浅接触阴影。三视图不可以有分割线，比例是16:9，左侧为角色胸部以上特写大图，占画面约 40% 宽度，用于展示面部、发型、表情、眼神、上半身服装和配饰细节，右侧为同一角色的三视图，占画面约 60% 宽度，依次展示正面全身、侧面全身、背面全身。"""

SCENE_PROMPT_PREFIX = """生成四宫格画面，展示同一个场景中的四个不同视角。左上角为正视图，主体正面清晰可见，构图居中，细节完整；右上角为俯视图，从高空俯视整体空间布局，展示环境关系和场景结构；左下角为背视图，从主体后方观察，突出背部轮廓、空间纵深和环境延展；右下角为侧视图，从主体侧面观察，展示主体比例、层次和空间关系。四个画面保持同一场景、同一光照、同一色调、同一时间状态。不输出文字信息。

1. 只出现场景，不出现人物、道具等无关内容,
2. 必须只展示静态事物，不能包含人，动物等可以自行运行的事物
3. 无动态、特效、技能、光效及战斗相关描写。"""

ASSET_PROMPT = """
通看完整视频，建立少而准、全局去重的视觉资产库。先在内部判断出现次数，只输出在至少两个独立镜头或不连续时间段中真实可见的资产，不输出次数和判断过程。连续停留只算一次；仅被台词、字幕或包装文字提到不算出现。同一资产的机位、动作、光线或状态发生变化，仍只能输出一次。

description 只输出资产自身可变的视觉内容，不重复三视图、四宫格、画幅等固定版式，程序会自动补齐。内容应细致、具体、有辨识度，但不写当前镜头的动作、临时表情和构图，也不猜测画面无法确认的属性。

人物包含人类、动物和群像：
- label 只表示资产形态：单个人类填“人物”，单个动物填“动物”，多人或动物群体填“群像”，不要判断主次或重要程度。
- 单个人类和单个动物的 description 共用下面14行，字段名和顺序不可改变、合并或省略，无法确认的字段保留字段名并将内容填无，不添加其他字段。：
  - **时代基底**: 真实历史、现代、未来或架空等时代背景
  - **国家/朝代**: 可确认的国家、地区、朝代或文化体系
  - **人种**: 人类填写人种或族裔；动物填写物种和品种
  - **类型基底**: 写实、奇幻、科幻或其他世界观类型
  - **脸型**: 人类详细描述脸型、五官、眼神和稳定面部标记；动物描述头脸轮廓、眼睛、口鼻和耳部结构
  - **发型**: 人类描述发型发色与发质；动物描述毛发、鬃毛、羽毛或鳞片的颜色、长度、纹理和分布
  - **耳饰**: 人类填写耳饰；动物填写耳部固定配饰，没有则留空
  - **身材**: 身高或体长、骨架、胖瘦、肌肉、四肢比例和稳定体态
  - **头身比**: 人类填写写实头身比例；动物填写头部与躯干的整体比例
  - **上身着装**: 人类填写上装；动物填写覆盖头颈、胸背或前半身的固定鞍具、护甲和配饰
  - **下身着装**: 人类填写下装；动物填写覆盖腹部、后半身或后肢的固定装具和配饰
  - **鞋子**: 人类填写鞋履；动物描述爪、蹄、足部形态或固定足部护具
  - **性别**: 性别
  - **年龄**: 幼年、青年、中年、老年或可确认的年龄范围
  每项只写跨镜头稳定可见的体貌和装束，不写当前动作、姿势、临时表情、伤势变化或镜头构图。服装和装具应写清颜色、材质、结构、纹样、磨损和层次。无法确认的字段保留字段名并将内容填无，不添加其他字段。
- 群像的 description 必须严格使用下面15行，字段名和顺序不可改变、合并或省略：
  - **人物特征**: 群体身份、共同神态、整体气质和稳定视觉特征
  - **年龄段**: 年龄范围和主要年龄构成
  - **性别**: 性别构成
  - **种族**: 人种、族裔、物种或灵体等本质类型
  - **人数规模**: 可见或合理概括的人数级别
  - **身材**: 共同体型以及高矮胖瘦的自然差异范围
  - **脸型**: 主要脸型及面部轮廓差异
  - **眉毛**: 主要眉形、颜色及个体差异
  - **眼镜**: 眼镜特征，没有则写“无”
  - **鼻子**: 主要鼻型及个体差异
  - **嘴唇**: 主要唇形、唇色及个体差异
  - **皮肤**: 肤色、皮肤质感和稳定表面特征
  - **特殊标记**: 胡须、伤疤、光核或其他稳定识别标记，没有则写“无”
  - **发型**: 发型、发色、整理方式及个体差异
  - **服饰和道具**: 服装体系、材质、配色、结构、磨损、阶层或阵营特征，以及群体共有道具
  每一项先写群体共性，再写合理的个体差异范围。只描述稳定可见外观，不写队列、冲锋、行走、饮酒等当前动作或镜头状态；不要把某个个体的偶然特征写成全体特征。无法辨识的字段仍须保留，并明确写“无法辨识”。

场景只按真正不同的叙事地点建档，同一地点的不同角度、景别和局部区域必须合并。description 必须写成一段连续、可从不同视角重建同一空间的场景说明，不使用字段列表，并严格按以下逻辑组织：
1. 首先说明横向长幅全景、真实比例和水平平面投影；直线、地平线和垂直物体保持笔直，明确排除鱼眼、球面、桶形和小行星畸变。
2. 说明场景名称、时代风格、室内或室外、整体规模、空间外形以及主要延伸方向或中轴线。
3. 按近景、中景、远景顺序描述地面、建筑、地形和固定陈设；每个重要元素都必须写清左、右、中央、前、后、上、下等准确位置，以及它与其他元素的相对关系。
4. 对成组、重复、对称或沿路径排列的元素，写清数量、间距、排列方向和覆盖范围，保证四个视角中的空间拓扑一致。
5. 最后写明机位位置、观察方向、地平线高度、稳定光源、天气和主色调；必要时用一句话汇总所有关键元素的空间关系。
只描述固定空间及其组成部分，不出现人物、动物、临时道具、动作、战斗、技能或特效。固定建筑陈设不属于需要排除的无关道具。不要用“旁边、附近、若干”等无法重建空间的模糊表达。

物品只保留跨镜头反复可见、需要保持同一造型的关键道具。description 使用一段连贯的道具描述，写清品类、整体轮廓与比例、材质、颜色、结构部件、纹样或准确可见文字、表面质感、磨损和独有识别特征。同一产品的不同角度、开合状态和轻微文字识别差异必须合并。

忽略路人、普通摆设、一次性群像、一次性地点、一次性道具和无关细节。名称简短稳定。
""".strip()

PROMPT_TEMPLATE = """
你是专业影视导演和视频生成提示词逆向工程师。输入是一段带原始音轨的完整视频，以及当前片段可引用的关键资产。
请提取能够准确复现原视频的制作信息，不写剧情摘要，不罗列无关细节。

1. 按真实切镜拆分镜头并给出连续时间段，镜头描述需包含机位、景别、主体动作、
   表情、空间关系、光线和关键道具。
2. 准确归纳全片视觉风格、摄影规格、色彩光影和空间前置条件；描述必须具体、
   可执行，不能只写“电影感”“高级感”。
   约10秒的视频应提供接近专业分镜脚本的信息密度，通常形成约800-1500字的最终制作提示词。
3. 完整听取音轨，对白逐字记录并归属说话人，环境音与背景音乐分开。对白识别必须执行下面的证据链，
   不得在第一次听觉识别失败后停止：
   - 音轨清晰时以实际说话内容为准；一旦遇到含混、重叠、方言、噪声或音乐遮盖，必须检查该对白对应
     时间段内的画面字幕、对白条、气泡文字等逐帧可见文字，并结合前后对白与镜头中的说话人交叉核对。
   - 画面存在清晰可读的对白字幕时，必须用字幕补足听不清的内容；不得用“[听不清]”“无法识别”
     或空对白替代已经可从字幕确认的文字。包装文案、水印和与对白无关的画面文字不能冒充对白。
   - 只有确认音轨无法辨认，并且对应时间段没有任何清晰可读的对白字幕时，才允许在确实缺失的
     局部标记“[听不清]”；其余已辨认文字必须保留，禁止整句偷懒标记，也严禁凭剧情编造。
   返回 JSON 前，必须对每一处“[听不清]”重新检查对应画面字幕；只返回最终结论，不输出检查过程。
4. 只引用给定关键资产，使用真实 asset_id。资产描述仅用于识别，不要在每个镜头机械复述完整人物设定。
5. 内容要有足够制作细节，但同一信息只写一次。严格返回约定 JSON，confidence 使用 0-1。
""".strip()

ASSET_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "characters": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "label": {"type": "string", "enum": ["人物", "动物", "群像"]}, "description": {"type": "string"}}, "required": ["name", "label", "description"]}},
        "scenes": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "description"]}},
        "objects": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "description"]}},
    },
    "required": ["characters", "scenes", "objects"],
}

DIALOGUE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {"speaker_asset_id": {"type": "string"}, "speaker_name": {"type": "string"}, "delivery": {"type": "string"}, "text": {"type": "string"}},
    "required": ["speaker_asset_id", "speaker_name", "delivery", "text"],
}

PROMPT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "asset_refs": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"asset_id": {"type": "string"}, "asset_name": {"type": "string"}, "asset_type": {"type": "string", "enum": ["character", "scene", "object"]}}, "required": ["asset_id", "asset_name", "asset_type"]}},
        "style": {"type": "object", "additionalProperties": False, "properties": {"visual_style": {"type": "string"}, "cinematography": {"type": "string"}, "color_tone": {"type": "string"}}, "required": ["visual_style", "cinematography", "color_tone"]},
        "global_conditions": {"type": "object", "additionalProperties": False, "properties": {"time_weather": {"type": "string"}, "environment_light": {"type": "string"}, "spatial_relationships": {"type": "string"}}, "required": ["time_weather", "environment_light", "spatial_relationships"]},
        "audio": {"type": "object", "additionalProperties": False, "properties": {"has_bgm": {"type": "boolean"}, "bgm_description": {"type": "string"}}, "required": ["has_bgm", "bgm_description"]},
        "shots": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"order": {"type": "integer"}, "start_seconds": {"type": "number"}, "end_seconds": {"type": "number"}, "title": {"type": "string"}, "camera": {"type": "string"}, "description": {"type": "string"}, "environment_sound": {"type": "string"}, "dialogues": {"type": "array", "items": DIALOGUE_SCHEMA}}, "required": ["order", "start_seconds", "end_seconds", "title", "camera", "description", "environment_sound", "dialogues"]}},
        "transition": {"type": "string"},
        "effects": {"type": "object", "additionalProperties": False, "properties": {"forbidden": {"type": "string"}, "allowed": {"type": "string"}}, "required": ["forbidden", "allowed"]},
        "confidence": {"type": "number"},
    },
    "required": ["asset_refs", "style", "global_conditions", "audio", "shots", "transition", "effects", "confidence"],
}
