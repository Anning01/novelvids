"""分镜数据模型 - 用于AI视频生成的结构化提示词。

核心公式：[摄影技术] + [主体] + [动作] + [环境背景] + [风格与氛围] + [音频指令]

支持的视频生成平台：
- Vidu Q2: 强调细腻面部表情、平滑推拉镜头
- Kling 2.5: 电影感动作视频
- Veo 3.1: 原生音频生成、多参考图
- Sora 2: 物理感知、复杂场景
"""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ============== 枚举类型 ==============


class ShotSize(StrEnum):
    """景别 - 镜头与主体的距离。"""

    EXTREME_CLOSE_UP = "extreme_close_up"  # 特写：眼睛、嘴唇等局部
    CLOSE_UP = "close_up"  # 近景：头部+肩膀
    MEDIUM_CLOSE_UP = "medium_close_up"  # 中近景：胸部以上
    MEDIUM_SHOT = "medium_shot"  # 中景：腰部以上
    COWBOY_SHOT = "cowboy_shot"  # 牛仔镜头：大腿以上（常用于西部片）
    MEDIUM_LONG_SHOT = "medium_long_shot"  # 中远景：膝盖以上
    FULL_SHOT = "full_shot"  # 全景：完整人物
    LONG_SHOT = "long_shot"  # 远景：人物+环境
    EXTREME_LONG_SHOT = "extreme_long_shot"  # 大远景：广阔环境，人物很小
    ESTABLISHING_SHOT = "establishing_shot"  # 建立镜头：展示场景全貌


class CameraAngle(StrEnum):
    """相机角度。"""

    EYE_LEVEL = "eye_level"  # 平视角：标准视角
    LOW_ANGLE = "low_angle"  # 仰拍：使主体显得强大、威严
    HIGH_ANGLE = "high_angle"  # 俯拍：使主体显得渺小、脆弱
    BIRDS_EYE = "birds_eye"  # 鸟瞰：正上方俯视
    WORMS_EYE = "worms_eye"  # 蚂蚁视角：正下方仰视
    DUTCH_ANGLE = "dutch_angle"  # 荷兰角/倾斜角：制造不安感
    OVER_THE_SHOULDER = "over_the_shoulder"  # 过肩镜头：对话常用
    POV = "pov"  # 第一人称视角


class CameraMovement(StrEnum):
    """相机运动类型。"""

    STATIC = "static"  # 静态镜头
    PAN_LEFT = "pan_left"  # 水平摇左
    PAN_RIGHT = "pan_right"  # 水平摇右
    TILT_UP = "tilt_up"  # 垂直摇上
    TILT_DOWN = "tilt_down"  # 垂直摇下
    DOLLY_IN = "dolly_in"  # 推镜头（向前移动）
    DOLLY_OUT = "dolly_out"  # 拉镜头（向后移动）
    TRUCK_LEFT = "truck_left"  # 横移左
    TRUCK_RIGHT = "truck_right"  # 横移右
    PEDESTAL_UP = "pedestal_up"  # 升镜头
    PEDESTAL_DOWN = "pedestal_down"  # 降镜头
    ZOOM_IN = "zoom_in"  # 变焦推近
    ZOOM_OUT = "zoom_out"  # 变焦拉远
    ARC_LEFT = "arc_left"  # 弧形左移
    ARC_RIGHT = "arc_right"  # 弧形右移
    TRACKING = "tracking"  # 跟踪镜头
    CRANE_UP = "crane_up"  # 摇臂上升
    CRANE_DOWN = "crane_down"  # 摇臂下降
    HANDHELD = "handheld"  # 手持晃动
    STEADICAM = "steadicam"  # 稳定器跟拍
    WHIP_PAN = "whip_pan"  # 急速横摇（用于转场）
    PUSH_IN = "push_in"  # 缓慢推进
    PULL_BACK = "pull_back"  # 缓慢拉远
    ORBIT = "orbit"  # 环绕
    ROLL = "roll"  # 翻滚


class LensType(StrEnum):
    """镜头焦距类型。"""

    WIDE_ANGLE = "wide_angle"  # 广角 (16-35mm)：夸张透视，适合场景
    NORMAL = "normal"  # 标准 (35-50mm)：接近人眼
    PORTRAIT = "portrait"  # 人像 (85mm)：适合人物特写
    TELEPHOTO = "telephoto"  # 长焦 (100-200mm)：压缩空间
    MACRO = "macro"  # 微距：细节特写
    ANAMORPHIC = "anamorphic"  # 变形宽银幕：电影感


class LightingStyle(StrEnum):
    """光线风格。"""

    NATURAL = "natural"  # 自然光
    GOLDEN_HOUR = "golden_hour"  # 黄金时刻（日出日落）
    BLUE_HOUR = "blue_hour"  # 蓝调时刻
    HIGH_KEY = "high_key"  # 高调光（明亮、轻快）
    LOW_KEY = "low_key"  # 低调光（暗调、戏剧性）
    DRAMATIC = "dramatic"  # 戏剧性光线
    SOFT = "soft"  # 柔光
    HARD = "hard"  # 硬光（强对比）
    BACKLIT = "backlit"  # 逆光
    RIM_LIGHT = "rim_light"  # 轮廓光
    NEON = "neon"  # 霓虹灯光
    CANDLELIGHT = "candlelight"  # 烛光
    MOONLIGHT = "moonlight"  # 月光
    OVERCAST = "overcast"  # 阴天散射光
    VOLUMETRIC = "volumetric"  # 体积光（丁达尔效应）


class MoodAtmosphere(StrEnum):
    """情绪氛围。"""

    PEACEFUL = "peaceful"  # 平和
    TENSE = "tense"  # 紧张
    ROMANTIC = "romantic"  # 浪漫
    MELANCHOLIC = "melancholic"  # 忧郁
    MYSTERIOUS = "mysterious"  # 神秘
    JOYFUL = "joyful"  # 欢快
    DRAMATIC = "dramatic"  # 戏剧性
    HORRIFIC = "horrific"  # 恐怖
    EPIC = "epic"  # 史诗
    INTIMATE = "intimate"  # 亲密
    CHAOTIC = "chaotic"  # 混乱
    SERENE = "serene"  # 宁静
    NOSTALGIC = "nostalgic"  # 怀旧
    SUSPENSEFUL = "suspenseful"  # 悬疑


class VideoStyle(StrEnum):
    """视频风格。"""

    CINEMATIC = "cinematic"  # 电影感
    PHOTOREALISTIC = "photorealistic"  # 照片写实
    ANIME = "anime"  # 动漫风格
    CARTOON = "cartoon"  # 卡通
    NOIR = "noir"  # 黑色电影
    VINTAGE = "vintage"  # 复古
    DOCUMENTARY = "documentary"  # 纪录片风格
    MUSIC_VIDEO = "music_video"  # MV风格
    COMMERCIAL = "commercial"  # 广告片风格
    FANTASY = "fantasy"  # 奇幻
    SCI_FI = "sci_fi"  # 科幻
    HORROR = "horror"  # 恐怖片风格
    ACTION = "action"  # 动作片风格


class AspectRatio(StrEnum):
    """画面比例。"""

    RATIO_16_9 = "16:9"  # 标准横屏
    RATIO_9_16 = "9:16"  # 竖屏（短视频）
    RATIO_1_1 = "1:1"  # 正方形
    RATIO_4_3 = "4:3"  # 传统电视
    RATIO_21_9 = "21:9"  # 超宽银幕
    RATIO_2_39_1 = "2.39:1"  # 变形宽银幕


class MotionSpeed(StrEnum):
    """动作速度。"""

    SLOW_MOTION = "slow_motion"  # 慢动作
    NORMAL = "normal"  # 正常速度
    FAST_MOTION = "fast_motion"  # 快动作
    TIME_LAPSE = "time_lapse"  # 延时摄影
    FREEZE_FRAME = "freeze_frame"  # 定格


# ============== 分镜组件模型 ==============


class CameraSettings(BaseModel):
    """相机设置 - 控制镜头的技术参数。"""

    shot_size: ShotSize = Field(
        default=ShotSize.MEDIUM_SHOT,
        description="景别：镜头与主体的距离",
    )
    camera_angle: CameraAngle = Field(
        default=CameraAngle.EYE_LEVEL,
        description="相机角度",
    )
    camera_movement: CameraMovement = Field(
        default=CameraMovement.STATIC,
        description="相机运动类型",
    )
    movement_speed: str = Field(
        default="smooth",
        description="运动速度：slow/smooth/fast",
    )
    lens_type: LensType = Field(
        default=LensType.NORMAL,
        description="镜头焦距类型",
    )
    depth_of_field: str = Field(
        default="normal",
        description="景深：shallow(浅景深)/normal/deep(深景深)",
    )
    focus_target: str | None = Field(
        default=None,
        description="对焦目标，如 'character face', 'object in hand'",
    )


class SubjectAction(BaseModel):
    """主体与动作 - 镜头的核心内容。"""

    # 主体信息
    subject_type: Literal["person", "scene", "item", "multiple"] = Field(
        default="person",
        description="主体类型",
    )
    subject_description: str = Field(
        description="主体描述（英文）",
    )
    asset_refs: list[UUID] = Field(
        default_factory=list,
        description="关联的资产ID列表（用于一致性控制）",
    )

    # 动作信息
    action: str = Field(
        description="主体动作描述（英文），使用具体动词",
    )
    action_intensity: str = Field(
        default="normal",
        description="动作强度：subtle/normal/intense",
    )
    emotion: str | None = Field(
        default=None,
        description="情感表达，如 'micro-expressions of relief', 'subtle smile'",
    )
    body_language: str | None = Field(
        default=None,
        description="肢体语言描述",
    )


class EnvironmentSettings(BaseModel):
    """环境设置 - 场景背景和氛围。"""

    location: str = Field(
        description="场景位置描述（英文）",
    )
    scene_asset_ref: UUID | None = Field(
        default=None,
        description="关联的场景资产ID",
    )
    time_of_day: str = Field(
        default="day",
        description="时间：dawn/morning/noon/afternoon/dusk/night",
    )
    weather: str | None = Field(
        default=None,
        description="天气：sunny/cloudy/rainy/snowy/foggy/stormy",
    )
    lighting: LightingStyle = Field(
        default=LightingStyle.NATURAL,
        description="光线风格",
    )
    lighting_details: str | None = Field(
        default=None,
        description="光线细节，如 'warm 3200K', 'cool blue moonlight'",
    )
    atmosphere_elements: list[str] = Field(
        default_factory=list,
        description="氛围元素：fog, dust_motes, rain, snow, sparks, smoke",
    )


class StyleSettings(BaseModel):
    """风格设置 - 视觉美学和情绪。"""

    video_style: VideoStyle = Field(
        default=VideoStyle.CINEMATIC,
        description="视频整体风格",
    )
    mood: MoodAtmosphere = Field(
        default=MoodAtmosphere.PEACEFUL,
        description="情绪氛围",
    )
    color_grading: str | None = Field(
        default=None,
        description="调色风格：teal-orange, desaturated, warm, cold",
    )
    film_grain: bool = Field(
        default=False,
        description="是否添加胶片颗粒",
    )
    contrast: str = Field(
        default="normal",
        description="对比度：low/normal/high",
    )
    saturation: str = Field(
        default="normal",
        description="饱和度：desaturated/normal/vivid",
    )


class AudioSettings(BaseModel):
    """音频设置 - 对话、音效、环境音。

    优先级：对话 > 音效 > 环境 > 音乐
    """

    # 对话
    dialogue: str | None = Field(
        default=None,
        description="角色对话内容",
    )
    dialogue_speaker: str | None = Field(
        default=None,
        description="说话者名称或描述",
    )
    dialogue_tone: str | None = Field(
        default=None,
        description="语气：whisper/normal/shout/emotional",
    )

    # 音效 (SFX)
    sound_effects: list[str] = Field(
        default_factory=list,
        description="同步音效列表，如 ['footsteps on wet pavement', 'door creaking']",
    )

    # 环境音 (Ambient)
    ambient_sounds: list[str] = Field(
        default_factory=list,
        description="背景环境音，如 ['city traffic', 'birds chirping', 'wind']",
    )

    # 背景音乐
    background_music: str | None = Field(
        default=None,
        description="背景音乐描述，如 'soft piano melody', 'tense orchestral'",
    )
    music_volume: str = Field(
        default="normal",
        description="音乐音量：low/normal/high，对话时应设为low",
    )


class TechnicalSettings(BaseModel):
    """技术参数 - 输出规格。"""

    duration: float = Field(
        default=4.0,
        ge=2.0,
        le=15.0,
        description="镜头时长（秒）：2-15秒",
    )
    aspect_ratio: AspectRatio = Field(
        default=AspectRatio.RATIO_16_9,
        description="画面比例",
    )
    motion_speed: MotionSpeed = Field(
        default=MotionSpeed.NORMAL,
        description="动作速度",
    )
    resolution: str = Field(
        default="1080p",
        description="分辨率：720p/1080p/4K",
    )
    fps: int = Field(
        default=24,
        ge=24,
        le=60,
        description="帧率",
    )


class NegativePrompt(BaseModel):
    """负面提示词 - 要避免的元素。"""

    avoid_elements: list[str] = Field(
        default_factory=list,
        description="要避免的元素：blurry, distorted, watermark, text, etc.",
    )
    avoid_artifacts: bool = Field(
        default=True,
        description="避免AI伪影",
    )
    avoid_text: bool = Field(
        default=True,
        description="避免画面中出现文字",
    )


# ============== 分镜主模型 ==============


class Shot(BaseModel):
    """单个分镜/镜头 - 完整的视频生成指令。

    核心公式：[摄影技术] + [主体] + [动作] + [环境背景] + [风格与氛围] + [音频指令]
    """

    # 基础信息
    sequence: int = Field(
        description="镜头序号（从1开始）",
    )
    name: str | None = Field(
        default=None,
        description="镜头名称/标题，如 '开场远景', '对话特写'",
    )
    description_cn: str = Field(
        description="中文描述（用于展示）",
    )

    # 原文关联
    source_text: str | None = Field(
        default=None,
        description="对应的原文片段",
    )
    source_line_start: int | None = Field(
        default=None,
        description="原文起始行号",
    )
    source_line_end: int | None = Field(
        default=None,
        description="原文结束行号",
    )

    # 核心组件
    camera: CameraSettings = Field(
        default_factory=CameraSettings,
        description="相机设置",
    )
    subject: SubjectAction = Field(
        description="主体与动作",
    )
    environment: EnvironmentSettings = Field(
        description="环境设置",
    )
    style: StyleSettings = Field(
        default_factory=StyleSettings,
        description="风格设置",
    )
    audio: AudioSettings = Field(
        default_factory=AudioSettings,
        description="音频设置",
    )
    technical: TechnicalSettings = Field(
        default_factory=TechnicalSettings,
        description="技术参数",
    )
    negative: NegativePrompt = Field(
        default_factory=NegativePrompt,
        description="负面提示词",
    )

    # 参考图（用于保持一致性）
    reference_images: list[str] = Field(
        default_factory=list,
        description="参考图路径列表（最多3张）",
    )
    start_frame: str | None = Field(
        default=None,
        description="起始帧图片路径（用于首尾帧控制）",
    )
    end_frame: str | None = Field(
        default=None,
        description="结束帧图片路径",
    )

    # 转场
    transition_in: str | None = Field(
        default=None,
        description="入场转场效果：cut/fade/dissolve/wipe",
    )
    transition_out: str | None = Field(
        default=None,
        description="出场转场效果",
    )

    # 平台优化提示词（包含 {ref:id} 占位符）
    platform_prompt: str | None = Field(
        default=None,
        description="针对目标平台优化的提示词，包含资产引用占位符",
    )

    # 视频生成任务状态
    video_task_id: str | None = Field(
        default=None,
        description="视频生成任务ID（来自vidu/doubao等平台）",
    )
    video_task_platform: str | None = Field(
        default=None,
        description="视频生成平台：vidu/doubao",
    )
    video_task_status: str | None = Field(
        default=None,
        description="视频任务状态：pending/processing/success/failed",
    )
    video_task_progress: float = Field(
        default=0,
        description="视频生成进度（0-100）",
    )
    video_url: str | None = Field(
        default=None,
        description="生成的视频URL/本地路径",
    )
    video_error: str | None = Field(
        default=None,
        description="视频生成失败时的错误信息",
    )

    def build_prompt(self, platform: str = "veo") -> str:
        """根据目标平台构建完整的提示词。

        Args:
            platform: 目标平台 veo/vidu/kling/sora

        Returns:
            构建好的英文提示词
        """
        parts = []

        # 1. 摄影技术
        camera_parts = []
        camera_parts.append(self.camera.shot_size.value.replace("_", " "))
        if self.camera.camera_angle != CameraAngle.EYE_LEVEL:
            camera_parts.append(self.camera.camera_angle.value.replace("_", " "))
        if self.camera.camera_movement != CameraMovement.STATIC:
            camera_parts.append(self.camera.camera_movement.value.replace("_", " "))
        if self.camera.lens_type != LensType.NORMAL:
            camera_parts.append(f"{self.camera.lens_type.value.replace('_', ' ')} lens")
        parts.append(", ".join(camera_parts))

        # 2. 主体与动作
        subject_parts = [self.subject.subject_description]
        subject_parts.append(self.subject.action)
        if self.subject.emotion:
            subject_parts.append(f"with {self.subject.emotion}")
        if self.subject.body_language:
            subject_parts.append(self.subject.body_language)
        parts.append(". ".join(subject_parts))

        # 3. 环境
        env_parts = [self.environment.location]
        if self.environment.time_of_day != "day":
            env_parts.append(f"at {self.environment.time_of_day}")
        if self.environment.weather:
            env_parts.append(self.environment.weather)
        if self.environment.lighting_details:
            env_parts.append(self.environment.lighting_details)
        if self.environment.atmosphere_elements:
            env_parts.append(", ".join(self.environment.atmosphere_elements))
        parts.append(", ".join(env_parts))

        # 4. 风格
        style_parts = [self.style.video_style.value]
        style_parts.append(self.style.mood.value)
        if self.style.color_grading:
            style_parts.append(f"{self.style.color_grading} color grade")
        if self.style.film_grain:
            style_parts.append("film grain")
        if self.style.contrast != "normal":
            style_parts.append(f"{self.style.contrast} contrast")
        parts.append(", ".join(style_parts))

        # 5. 音频（根据平台决定是否添加）
        if platform in ("veo", "sora"):
            audio_parts = []
            if self.audio.dialogue:
                speaker = self.audio.dialogue_speaker or "Character"
                audio_parts.append(f'{speaker} says: "{self.audio.dialogue}"')
            if self.audio.sound_effects:
                for sfx in self.audio.sound_effects:
                    audio_parts.append(f"SFX: {sfx}")
            if self.audio.ambient_sounds:
                audio_parts.append(f"Ambient: {', '.join(self.audio.ambient_sounds)}")
            if audio_parts:
                parts.append(". ".join(audio_parts))

        # 组合
        prompt = ". ".join(parts) + "."

        return prompt

    def build_negative_prompt(self) -> str:
        """构建负面提示词。"""
        negatives = list(self.negative.avoid_elements)
        if self.negative.avoid_artifacts:
            negatives.extend(["blurry", "distorted", "deformed", "artifacts"])
        if self.negative.avoid_text:
            negatives.extend(["text", "watermark", "logo", "subtitle"])
        return ", ".join(negatives)


class Storyboard(BaseModel):
    """分镜脚本 - 一个章节的完整分镜。"""

    # 关联信息
    chapter_id: UUID = Field(
        description="章节ID",
    )
    chapter_number: int = Field(
        description="章节序号",
    )
    chapter_title: str = Field(
        description="章节标题",
    )

    # 分镜列表
    shots: list[Shot] = Field(
        default_factory=list,
        description="分镜列表",
    )

    # 全局设置（可被单个镜头覆盖）
    global_style: StyleSettings = Field(
        default_factory=StyleSettings,
        description="全局风格设置",
    )
    global_aspect_ratio: AspectRatio = Field(
        default=AspectRatio.RATIO_16_9,
        description="全局画面比例",
    )

    # 元数据
    total_duration: float = Field(
        default=0.0,
        description="总时长（秒）",
    )
    created_at: str | None = Field(
        default=None,
        description="创建时间",
    )
    updated_at: str | None = Field(
        default=None,
        description="更新时间",
    )

    def calculate_total_duration(self) -> float:
        """计算总时长。"""
        self.total_duration = sum(shot.technical.duration for shot in self.shots)
        return self.total_duration




# ============== 分镜生成请求/响应 ==============


class StoryboardGenerateRequest(BaseModel):
    """分镜生成请求。"""

    chapter_id: UUID = Field(
        description="章节ID",
    )
    max_shot_duration: float = Field(
        default=8.0,
        ge=4.0,
        le=15.0,
        description="单个镜头最大时长（秒）",
    )
    target_platform: str = Field(
        default="veo",
        description="目标平台：veo/vidu/kling/sora",
    )
    style_preset: VideoStyle = Field(
        default=VideoStyle.CINEMATIC,
        description="风格预设",
    )
    aspect_ratio: AspectRatio = Field(
        default=AspectRatio.RATIO_16_9,
        description="画面比例",
    )
    include_audio: bool = Field(
        default=True,
        description="是否包含音频指令",
    )


class StoryboardGenerateResponse(BaseModel):
    """分镜生成响应。"""

    storyboard: Storyboard = Field(
        description="生成的分镜脚本",
    )
    shot_count: int = Field(
        description="镜头数量",
    )
    total_duration: float = Field(
        description="总时长（秒）",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="警告信息",
    )
