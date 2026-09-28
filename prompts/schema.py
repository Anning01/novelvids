"""Model-facing schema annotations; stored/API schema identities remain unchanged."""

from copy import deepcopy
from prompts.catalog import catalog, text
import json

ANNOTATION_KEYS = {
    "用于在 Scene 中嵌套展示资产的简化模型": "schema_000",
    "一次生成请求内的小镜头；编号和起止时间由渲染器产生。": "schema_001",
    "专业视频分镜提示词的结构化内容。": "schema_002",
    "完整的故事板，包含多个分镜": "schema_003",
    "最基础的属性集合，不含大字段。\n用于列表(List)、关联查询(Relation)等轻量场景。": "schema_004",
    "完整的业务属性，包含 metadata 等大字段。\n用于创建、更新、详情。": "schema_005",
    "创建请求：chapter_id 必填": "schema_006",
    "全量更新": "schema_007",
    "局部更新：全字段可选": "schema_008",
    "列表输出：仅返回简要信息，提升加载速度。": "schema_009",
    "详情输出：返回包括正文在内的所有信息。": "schema_010",
    "对 metadata 中持久化的媒体引用重新签发（首尾帧与参考素材）。": "schema_011",
    "场景词的标准名称，如 '张三'": "schema_012",
    "该场景词在文中可能出现的别名，如 ['三哥', '张大侠']": "schema_013",
    "该实体的视觉描述字符串": "schema_014",
    "实体类型，用于构建专业 Prompt 的资产引用章节": "schema_015",
    "关联的资产ID，用于持久化分镜资产引用": "schema_016",
    "资产ID": "schema_017",
    "资产名称": "schema_018",
    "资产主图": "schema_019",
    "详细描述": "schema_020",
    "固有特征（语言由通用配置决定，用于 prompt）": "schema_021",
    "是否全局资产": "schema_022",
    "这些资产类型只保留名称引用，不在分镜中展开外貌设定；其他类型保持默认展开": "schema_023",
    "分镜序列号": "schema_024",
    "镜头主提示词，用一句可直接生成的视频描述概括主体、核心动作与剧情结果；当人物台词、旁白或内心 OS 是本镜头关键戏剧信息时，必须明确其声音主体和作用，不得只写抽象情绪或剧情标题": "schema_025",
    "镜头时长，格式如 3s、4s 或 8s，范围 1-30 秒": "schema_026",
    "景别与机位，如‘中景正面机位’或‘过肩镜头’": "schema_027",
    "贯穿该镜头的视觉风格，不描述剧情动作": "schema_028",
    "根据题材明确禁止的廉价或违和视觉特效": "schema_029",
    "时间、天气与总体光线条件": "schema_030",
    "环境状态、光线层次与氛围变化": "schema_031",
    "当前镜头内人物、场景入口、主要陈设和机位之间的完整空间关系；必须写明在场人物的初始位置、朝向和动作起点；如承接相邻镜头，需把连续性转换为当前镜头内的具体状态": "schema_032",
    "【核心视觉描述】。逻辑约束：如果涉及 Defined Entities，必须使用 @实体名 (如 @张三)，严禁重复描述其外观。对于非预定义物体，必须进行极致的细节描述（材质、纹理、微动作）。": "schema_033",
    "【时间轴动作分解】。格式必须为 '开始时间-结束时间: 动作描述'。每个时间段都必须重新写明动作主体；已登记人物使用 @{完整实体名}，不得省略人物名或使用依赖上下文的代词。动作必须精确且符合物理逻辑。": "schema_034",
    "【格式与质感】。必须包含：快门角度(shutter angle)、胶片/数字格式(digital/film stock)、颗粒感(grain)、光晕(halation)等。例: '180° shutter; digital capture emulating Kodak Vision3 500T; heavy film grain.'": "schema_035",
    "【镜头与滤镜】。必须包含：焦段(Focal length)、镜头类型(Spherical/Anamorphic)、滤镜(Pro-Mist/Polarizer)。例: '35mm Anamorphic lens; Black Pro-Mist 1/8; slight edge distortion.'": "schema_036",
    "【光影与氛围】。必须包含：主光方向、光比(Key/Fill ratio)、具体的灯光工具(Bounce/Negative fill)、大气效果(Haze/Mist)。例: 'Rembrandt lighting from camera right; volumetric haze; negative fill on the left.'": "schema_037",
    "【调色与色板】。必须包含：高光(Highlights)、中间调(Mids)、暗部(Blacks/Shadows)的色彩倾向。例: 'Highlights: warm amber; Shadows: teal crush; Desaturated mids.'": "schema_038",
    "【运镜】。使用专业术语：Dolly, Truck, Pan, Tilt, Steadicam, Handheld。描述速度和稳定性。例: 'Slow push-in (Dolly forward) combined with subtle handheld shake.'": "schema_039",
    "【声音设计】。Diegetic (介质音) only。包含具体的音量(LUFS)描述、环境底噪、材质摩擦声。例: 'Diegetic: Heavy breathing (-15 LUFS), distant wind howling, footsteps on snow.'": "schema_040",
    "镜头内旁白与人物内心 OS；每项必须包含精确开始/结束时间、声音主体、语气和内容。是否允许使用及与对白的时间关系由当前分镜策略决定；没有时返回空数组": "schema_041",
    "镜头内人物台词；每项包含人物、语气和原文，无台词时返回空数组": "schema_042",
    "说明与相邻镜头的衔接意图，同时完整写明当前镜头内可见的收尾画面和剪辑点；不得只写‘承接上一镜头’等无法直接执行的描述": "schema_043",
    "允许使用的克制效果；无特殊效果时明确写自然光写实拍摄": "schema_044",
    "当前一次生成请求内的小镜头；只有明确需要内部切镜时填写，编号自动从1开始": "schema_045",
    "描述": "schema_046",
    "提示词": "schema_047",
    "时长": "schema_048",
    "元数据": "schema_049",
    "说话角色IDs，关联资产表": "schema_050",
    "该镜头涉及的资产列表": "schema_051",
    "所属章节": "schema_052",
    "提示词配置": "schema_053",
    "编辑器读取到的原提示词，用于防止覆盖并发修改": "schema_054",
    "分镜ID": "schema_055",
    "所属章节ID": "schema_056",
    "提示词参数配置": "schema_057",
    "新增人物、场景或道具基础设定。": "schema_058",
    "已有角色的章内形态；父资产确定类型，没有 asset_type、aliases 或 is_global 参数。": "schema_059",
    "一次模型响应同时返回全部资产类型。": "schema_060",
    "标准名称": "schema_061",
    "别名列表": "schema_062",
    "资产形态": "schema_063",
    "任务指定语言的剧情语义说明": "schema_064",
    "目标提示词语言的稳定视觉描述": "schema_065",
    "场景名称": "schema_066",
    "目标提示词语言的稳定场景视觉描述": "schema_067",
    "道具名称": "schema_068",
    "目标提示词语言的稳定道具视觉描述": "schema_069",
    "人物资产列表": "schema_070",
    "场景资产列表": "schema_071",
    "道具资产列表": "schema_072",
    "优先使用完整书稿；超长时按章节均匀取样，避免只分析故事开头。": "schema_073",
    "完成 Agent 项目的分章、书稿理解、人物入库与 1K 封面生成。": "schema_074",
    "人物标准名称": "schema_075",
    "人物别名": "schema_076",
    "人物在故事中的身份和作用": "schema_077",
    "人物性格、背景、动机与人物弧光的任务指定语言的概述": "schema_078",
    "按任务指定语言撰写的详细人物外观描述": "schema_079",
    "人物出现的章节序号": "schema_080",
    "3 至 6 个准确、简短的任务指定语言的题材或类型标签": "schema_081",
    "完整故事大纲，包含主线冲突、关键转折和结局走向": "schema_082",
    "推动主线的关键人物，通常为 3 至 10 位": "schema_083",
    "读取当前上下文与约束；chapter_offset 读取正文片段，changes_page 翻页查本会话实际操作记录。": "schema_084",
    "修改已授权资产或已有形态的图片 Prompt，保持其他字段和素材绑定。": "schema_085",
    "修改已授权分镜的 Prompt；程序完成局部编号、引用展开和一致性保存。": "schema_086",
    "查询当前项目的轻量目录；references_of 可查询对象的引用关系，不产生修改。": "schema_087",
    "新建或整篇重写前读取对应类型的系统规范；指定 target 时同时读取实际对象，类型以对象为准。": "schema_088",
    "读取已有对象详情和约束；空 targets 可读取指定章的正文及约束，chapter_offset 按字符分页。": "schema_089",
    "分页回查本会话原始对话或压缩引用；历史不替代当前对象及权限。": "schema_090",
    "精确替换已读取设定或分镜的提示词片段；保留其余内容并返回可撤销回执。": "schema_091",
    "创建人物(1)、场景(2)或道具(3)；先读取 get_creation_prompt_rules，提交完整视觉描述，服务端渲染参考图任务。": "schema_092",
    "原子执行设定与分镜增删改；相关新增用 client_ref 引用；只返回已成功保存的回执。": "schema_093",
    "撤销本会话已保存的一组操作，不覆盖后续编辑或关联。": "schema_094",
}
WIRE_NAMES = {
    "人物": "person",
    "动物": "animal",
    "群像": "group",
    "场景": "scene",
    "物品": "item",
}


def schema_annotation(value: str | None, language: str) -> str | None:
    key = ANNOTATION_KEYS.get(value)
    return catalog("schema.json", language)[key] if key else value


def localized_schema(schema: dict, language: str) -> dict:
    """Copy annotations and language-sensitive enum values, never mutate the source."""

    def visit(node):
        if isinstance(node, list):
            return [visit(item) for item in node]
        if not isinstance(node, dict):
            return node
        result = {key: visit(value) for key, value in node.items()}
        for key in ("description", "title"):
            if isinstance(node.get(key), str):
                result[key] = schema_annotation(node[key], language)
        if language == "en":
            if isinstance(node.get("enum"), list):
                result["enum"] = [
                    WIRE_NAMES.get(value, value) if isinstance(value, str) else value
                    for value in node["enum"]
                ]
            for key in ("const", "default"):
                if isinstance(node.get(key), str):
                    result[key] = WIRE_NAMES.get(node[key], node[key])
        return result

    return visit(deepcopy(schema))


def json_instruction(schema: dict, language: str) -> str:
    return text(
        "json_instruction",
        language,
        schema=json.dumps(localized_schema(schema, language), ensure_ascii=False),
    )
