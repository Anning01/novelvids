# 生成视频分镜

from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Any, Literal, Optional
from schemas._base import BaseResponse
from utils.enums import AssetTypeEnum, TaskStatusEnum


# ===========================
# 1. 定义输入数据结构 (场景词/实体)
# ===========================
class SceneEntity(BaseModel):
    name: str = Field(..., description="场景词的标准名称，如 '张三'")
    aliases: list[str] = Field(..., description="该场景词在文中可能出现的别名，如 ['三哥', '张大侠']")
    description: str = Field(..., description="该实体的视觉描述字符串")
    asset_type: Literal["人物", "场景", "物品"] = Field(
        "人物",
        description="实体类型，用于构建专业 Prompt 的资产引用章节",
    )
    asset_id: Optional[int] = Field(None, description="关联的资产ID，用于持久化分镜资产引用")


# --- Asset 侧模型 ---
class AssetSimple(BaseModel):
    """用于在 Scene 中嵌套展示资产的简化模型"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="资产ID")
    asset_type: AssetTypeEnum = Field(..., description=AssetTypeEnum.__doc__)
    canonical_name: str = Field(..., description="资产名称")
    main_image: Optional[str] = Field(None, description="资产主图")
    description: Optional[str] = Field(None, description="详细描述")
    base_traits: Optional[str] = Field(None, description="固有特征（语言由通用配置决定，用于 prompt）")
    is_global: Optional[bool] = Field(None, description="是否全局资产")


class SoraScenePromptConfig(BaseModel):
    """专业视频分镜提示词的结构化内容。"""

    sequence: int = Field(..., description="分镜序列号")
    description: str = Field(..., description="镜头标题，简短描述该镜头的核心事件")
    duration: str = Field(..., description="镜头时长，格式如 3s、4s 或 8s，范围 1-30 秒")
    shot_size_and_camera: str = Field(
        ...,
        description="景别与机位，如‘中景正面机位’或‘过肩镜头’",
    )

    visual_style: str = Field(
        ...,
        description="贯穿该镜头的视觉风格，不描述剧情动作",
    )
    effect_restrictions: list[str] = Field(
        ...,
        description="根据题材明确禁止的廉价或违和视觉特效",
    )
    time_setting: str = Field(..., description="时间、天气与总体光线条件")
    environment: str = Field(..., description="环境状态、光线层次与氛围变化")
    spatial_relationships: str = Field(
        ...,
        description="人物、场景入口、主要陈设和机位之间的空间关系",
    )
    # --- 核心内容 ---
    visual_prose: str = Field(
        ...,
        description="【核心视觉描述】。逻辑约束：如果涉及 Defined Entities，必须使用 @实体名 (如 @张三)，严禁重复描述其外观。对于非预定义物体，必须进行极致的细节描述（材质、纹理、微动作）。"
    )

    actions: list[str] = Field(
        ...,
        description="【时间轴动作分解】。格式必须为 '开始时间-结束时间: 动作描述'。例如 '0.0s-2.0s: @张三 turns head slowly.'。动作必须精确且符合物理逻辑。"
    )

    # --- 电影级参数 (参考官方 example.md) ---
    format_and_look: str = Field(
        ...,
        description="【格式与质感】。必须包含：快门角度(shutter angle)、胶片/数字格式(digital/film stock)、颗粒感(grain)、光晕(halation)等。例: '180° shutter; digital capture emulating Kodak Vision3 500T; heavy film grain.'"
    )

    lenses_and_filtration: str = Field(
        ...,
        description="【镜头与滤镜】。必须包含：焦段(Focal length)、镜头类型(Spherical/Anamorphic)、滤镜(Pro-Mist/Polarizer)。例: '35mm Anamorphic lens; Black Pro-Mist 1/8; slight edge distortion.'"
    )

    lighting_and_atmosphere: str = Field(
        ...,
        description="【光影与氛围】。必须包含：主光方向、光比(Key/Fill ratio)、具体的灯光工具(Bounce/Negative fill)、大气效果(Haze/Mist)。例: 'Rembrandt lighting from camera right; volumetric haze; negative fill on the left.'"
    )

    grade_and_palette: str = Field(
        ...,
        description="【调色与色板】。必须包含：高光(Highlights)、中间调(Mids)、暗部(Blacks/Shadows)的色彩倾向。例: 'Highlights: warm amber; Shadows: teal crush; Desaturated mids.'"
    )

    camera_movement: str = Field(
        ...,
        description="【运镜】。使用专业术语：Dolly, Truck, Pan, Tilt, Steadicam, Handheld。描述速度和稳定性。例: 'Slow push-in (Dolly forward) combined with subtle handheld shake.'"
    )

    sound_design: str = Field(
        ...,
        description="【声音设计】。Diegetic (介质音) only。包含具体的音量(LUFS)描述、环境底噪、材质摩擦声。例: 'Diegetic: Heavy breathing (-15 LUFS), distant wind howling, footsteps on snow.'"
    )

    dialogue: list[str] = Field(
        default_factory=list,
        description="镜头内人物台词；每项包含人物、语气和原文，无台词时返回空数组",
    )
    transition: str = Field(
        ...,
        description="与相邻镜头衔接的转场方式及连续性依据",
    )
    allowed_effects: list[str] = Field(
        default_factory=list,
        description="允许使用的克制效果；无特殊效果时明确写自然光写实拍摄",
    )

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, value: str) -> str:
        raw = value.strip().lower().removesuffix("s")
        try:
            seconds = float(raw)
        except ValueError as exc:
            raise ValueError("duration 必须是 1-30 秒的数值，如 4s") from exc
        if not 1 <= seconds <= 30:
            raise ValueError("duration 必须在 1-30 秒之间")
        normalized = str(int(seconds)) if seconds.is_integer() else str(seconds)
        return f"{normalized}s"

class Storyboard(BaseModel):
    """完整的故事板，包含多个分镜"""
    shots: list[SoraScenePromptConfig]


# --- 核心业务属性 (Internal Mixins) ---

class SceneProperties(BaseModel):
    """
    最基础的属性集合，不含大字段。
    用于列表(List)、关联查询(Relation)等轻量场景。
    """
    sequence: Optional[int] = Field(None, description="分镜序列号")
    description: Optional[str] = Field(None, description="描述")
    prompt: Optional[str] = Field(None, description="提示词")
    duration: Optional[float] = Field(None, description="时长")
    status: Optional[TaskStatusEnum] = Field(None, description=TaskStatusEnum.__doc__)


class SceneFullProperties(SceneProperties):
    """
    完整的业务属性，包含 metadata 等大字段。
    用于创建、更新、详情。
    """
    metadata: Optional[Any] = Field(None, description="元数据")
    asset_ids: Optional[list[int]] = Field(None, description="说话角色IDs，关联资产表")
    assets: Optional[list[AssetSimple]] = Field(None, description="该镜头涉及的资产列表")


class SceneGenerateCreate(BaseModel):
    """创建请求：chapter_id 必填"""
    chapter_id: int = Field(..., description="所属章节")

# --- 输入 Schema (In-bound) ---

class SceneCreate(SceneFullProperties):
    """创建请求：chapter_id 必填"""
    chapter_id: int = Field(..., description="所属章节")
    sequence: int = Field(..., description="分镜序列号")
    prompt: str = Field(..., description="提示词配置")


class SceneUpdate(SceneCreate):
    """全量更新"""
    pass


class ScenePatch(SceneFullProperties):
    """局部更新：全字段可选"""
    chapter_id: Optional[int] = Field(None, description="所属章节")
    sequence: Optional[int] = Field(None, description="分镜序列号")
    prompt: Optional[str] = Field(None, description="提示词配置")



# --- 输出 Schema (Out-bound) ---


class SceneBriefOut(SceneProperties, BaseResponse):
    """
    列表输出：仅返回简要信息，提升加载速度。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="分镜ID")


class SceneOut(SceneFullProperties, BaseResponse):
    """
    详情输出：返回包括正文在内的所有信息。
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="分镜ID")
    chapter_id: int = Field(..., description="所属章节ID")
    prompt_params: Optional[dict[str, Any]] = Field(None, description="提示词参数配置")
