# 生成视频分镜

from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Optional
from schemas._base import BaseResponse
from utils.enums import AssetTypeEnum, TaskStatusEnum, VideoModelTypeEnum


# ===========================
# 1. 定义输入数据结构 (场景词/实体)
# ===========================
class SceneEntity(BaseModel):
    name: str = Field(..., description="场景词的标准名称，如 '张三'")
    aliases: list[str] = Field(..., description="该场景词在文中可能出现的别名，如 ['三哥', '张大侠']")
    description: str = Field(..., description="该实体的视觉描述字符串")


class SoraScenePromptConfig(BaseModel):
    """生成视频分镜的提示词配置 - Sora"""

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



# --- 核心业务属性 (Internal Mixins) ---

class SceneProperties(BaseModel):
    """
    最基础的属性集合，不含大字段。
    用于列表(List)、关联查询(Relation)等轻量场景。
    """
    sequence: Optional[int] = Field(None, description="分镜序列号")
    description: Optional[str] = Field(None, description="描述")
    prompt: Optional[SoraScenePromptConfig] = Field(None, description="提示词")
    duration: Optional[float] = Field(None, description="时长")
    status: Optional[TaskStatusEnum] = Field(None, description=TaskStatusEnum.__doc__)


class SceneFullProperties(SceneProperties):
    """
    完整的业务属性，包含 metadata 等大字段。
    用于创建、更新、详情。
    """
    metadata: Optional[Any] = Field(None, description="元数据")
    asset_ids: Optional[list[int]] = Field(None, description="说话角色IDs，关联资产表")


# --- 输入 Schema (In-bound) ---

class SceneCreate(BaseModel):
    """创建请求：chapter_id 必填"""
    chapter_id: int = Field(..., description="所属章节")
    model: VideoModelTypeEnum = Field(..., description=VideoModelTypeEnum.__doc__)

class SceneUpdate(SceneFullProperties):
    """全量更新"""
    chapter_id: int = Field(..., description="所属章节")
    sequence: int = Field(..., description="分镜序列号")
    prompt: SoraScenePromptConfig = Field(..., description="提示词配置")


class ScenePatch(SceneFullProperties):
    """局部更新：全字段可选"""
    chapter_id: Optional[int] = Field(None, description="所属章节")
    sequence: Optional[int] = Field(None, description="分镜序列号")
    prompt: Optional[SoraScenePromptConfig] = Field(None, description="提示词配置")



# --- 输出 Schema (Out-bound) ---

# --- Asset 侧模型 ---
class AssetSimple(BaseModel):
    """用于在 Scene 中嵌套展示资产的简化模型"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="资产ID")
    asset_type: AssetTypeEnum = Field(..., description=AssetTypeEnum.__doc__)
    description: Optional[str] = Field(None, description="详细描述")
    base_traits: Optional[str] = Field(None, description="固有特征 (英文, 用于 prompt)")
    is_global: Optional[bool] = Field(None, description="是否全局资产")


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
    assets: Optional[list[AssetSimple]] = Field(None, description="该镜头涉及的资产列表")