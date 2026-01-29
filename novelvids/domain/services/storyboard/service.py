"""分镜切分服务。

将小说章节内容切分成多个分镜，每个分镜包含完整的视频生成指令。
"""

import logging
from uuid import UUID

from novelvids.domain.models.storyboard import (
    AspectRatio,
    AudioSettings,
    CameraAngle,
    CameraMovement,
    CameraSettings,
    EnvironmentSettings,
    LensType,
    LightingStyle,
    MoodAtmosphere,
    MotionSpeed,
    NegativePrompt,
    Shot,
    ShotSize,
    Storyboard,
    StoryboardGenerateRequest,
    StoryboardGenerateResponse,
    StyleSettings,
    SubjectAction,
    TechnicalSettings,
    VideoStyle,
)
from novelvids.domain.services.llm_client import OpenAICompatibleClient
from novelvids.domain.services.storyboard.prompts import (
    PLATFORM_PROMPT_TEMPLATES,
    STORYBOARD_GENERATION_PROMPT,
    STORYBOARD_JSON_SCHEMA,
    STORYBOARD_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class StoryboardService:
    """分镜切分服务。"""

    def __init__(self, llm_client: OpenAICompatibleClient):
        self.llm = llm_client

    async def generate_storyboard(
        self,
        chapter_id: UUID,
        chapter_number: int,
        chapter_title: str,
        chapter_content: str,
        person_assets: list[dict],
        scene_assets: list[dict],
        item_assets: list[dict],
        request: StoryboardGenerateRequest,
    ) -> StoryboardGenerateResponse:
        """生成章节的分镜脚本。

        Args:
            chapter_id: 章节ID
            chapter_number: 章节序号
            chapter_title: 章节标题
            chapter_content: 章节内容
            person_assets: 人物资产列表
            scene_assets: 场景资产列表
            item_assets: 物品资产列表
            request: 生成请求参数

        Returns:
            分镜生成响应
        """
        # 格式化资产信息
        person_assets_str = self._format_assets(person_assets, "person")
        scene_assets_str = self._format_assets(scene_assets, "scene")
        item_assets_str = self._format_assets(item_assets, "item")

        # 构建提示词
        prompt = STORYBOARD_GENERATION_PROMPT.format(
            chapter_number=chapter_number,
            person_assets=person_assets_str,
            scene_assets=scene_assets_str,
            item_assets=item_assets_str,
            text=chapter_content,
            min_duration=4.0,
            max_duration=request.max_shot_duration,
            aspect_ratio=request.aspect_ratio.value,
            style_preset=request.style_preset.value,
            target_platform=request.target_platform,
        )

        # 调用 LLM 生成分镜（使用结构化输出）
        shots_data = await self.llm.complete_json(
            prompt=prompt,
            json_schema=STORYBOARD_JSON_SCHEMA,
            system=STORYBOARD_SYSTEM_PROMPT,
            max_tokens=16000,
            max_continuations=3,
        )

        # 构建 Shot 对象列表
        shots = []
        warnings = []

        for i, shot_data in enumerate(shots_data.get("shots", []), start=1):
            try:
                shot = self._build_shot(
                    shot_data,
                    sequence=i,
                    person_assets=person_assets,
                    scene_assets=scene_assets,
                    item_assets=item_assets,
                    global_style=request.style_preset,
                    aspect_ratio=request.aspect_ratio,
                    include_audio=request.include_audio,
                )
                shots.append(shot)
            except Exception as e:
                logger.warning(f"Failed to build shot {i}: {e}")
                warnings.append(f"镜头 {i} 解析失败: {str(e)}")

        # 创建 Storyboard
        storyboard = Storyboard(
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            chapter_title=chapter_title,
            shots=shots,
            global_style=StyleSettings(video_style=request.style_preset),
            global_aspect_ratio=request.aspect_ratio,
        )
        storyboard.calculate_total_duration()

        return StoryboardGenerateResponse(
            storyboard=storyboard,
            shot_count=len(shots),
            total_duration=storyboard.total_duration,
            warnings=warnings,
        )

    def _format_assets(self, assets: list[dict], asset_type: str) -> str:
        """格式化资产信息为字符串。"""
        if not assets:
            return "（无）"

        lines = []
        for asset in assets:
            name = asset.get("canonical_name", "未知")
            aliases = asset.get("aliases", [])
            base_traits = asset.get("base_traits", "")
            description = asset.get("description", "")

            alias_str = f"（别名：{', '.join(aliases)}）" if aliases else ""
            lines.append(f"- {name}{alias_str}")
            if base_traits:
                lines.append(f"  英文特征：{base_traits}")
            if description:
                lines.append(f"  中文描述：{description}")

        return "\n".join(lines)

    def _build_shot(
        self,
        shot_data: dict,
        sequence: int,
        person_assets: list[dict],
        scene_assets: list[dict],
        item_assets: list[dict],
        global_style: VideoStyle,
        aspect_ratio: AspectRatio,
        include_audio: bool,
    ) -> Shot:
        """从解析的数据构建 Shot 对象。"""
        # 相机设置
        camera_data = shot_data.get("camera", {})
        camera = CameraSettings(
            shot_size=self._parse_enum(ShotSize, camera_data.get("shot_size"), ShotSize.MEDIUM_SHOT),
            camera_angle=self._parse_enum(CameraAngle, camera_data.get("camera_angle"), CameraAngle.EYE_LEVEL),
            camera_movement=self._parse_enum(
                CameraMovement, camera_data.get("camera_movement"), CameraMovement.STATIC
            ),
            movement_speed=camera_data.get("movement_speed", "smooth"),
            lens_type=self._parse_enum(LensType, camera_data.get("lens_type"), LensType.NORMAL),
            depth_of_field=camera_data.get("depth_of_field", "normal"),
            focus_target=self._empty_to_none(camera_data.get("focus_target")),
        )

        # 主体与动作
        subject_data = shot_data.get("subject", {})
        asset_refs = self._resolve_asset_refs(
            subject_data.get("asset_names", []),
            person_assets,
            scene_assets,
            item_assets,
        )
        # 映射 LLM 返回的 subject_type 到有效值
        raw_subject_type = subject_data.get("subject_type", "person")
        subject_type_map = {
            "character": "person",
            "characters": "multiple",
            "object": "item",
            "objects": "item",
            "location": "scene",
            "environment": "scene",
        }
        subject_type = subject_type_map.get(raw_subject_type, raw_subject_type)
        if subject_type not in ("person", "scene", "item", "multiple"):
            subject_type = "person"

        subject = SubjectAction(
            subject_type=subject_type,
            subject_description=subject_data.get("subject_description", "a person"),
            asset_refs=asset_refs,
            action=subject_data.get("action", "standing"),
            action_intensity=subject_data.get("action_intensity", "normal"),
            emotion=self._empty_to_none(subject_data.get("emotion")),
            body_language=self._empty_to_none(subject_data.get("body_language")),
        )

        # 环境设置
        env_data = shot_data.get("environment", {})
        scene_ref = self._find_asset_id(env_data.get("scene_name"), scene_assets)
        environment = EnvironmentSettings(
            location=env_data.get("location", "an indoor location"),
            scene_asset_ref=scene_ref,
            time_of_day=env_data.get("time_of_day", "day"),
            weather=self._empty_to_none(env_data.get("weather")),
            lighting=self._parse_enum(LightingStyle, env_data.get("lighting"), LightingStyle.NATURAL),
            lighting_details=self._empty_to_none(env_data.get("lighting_details")),
            atmosphere_elements=env_data.get("atmosphere_elements", []),
        )

        # 风格设置
        style_data = shot_data.get("style", {})
        style = StyleSettings(
            video_style=self._parse_enum(VideoStyle, style_data.get("video_style"), global_style),
            mood=self._parse_enum(MoodAtmosphere, style_data.get("mood"), MoodAtmosphere.PEACEFUL),
            color_grading=self._empty_to_none(style_data.get("color_grading")),
            film_grain=style_data.get("film_grain", False),
            contrast=style_data.get("contrast", "normal"),
            saturation=style_data.get("saturation", "normal"),
        )

        # 音频设置
        audio_data = shot_data.get("audio", {}) if include_audio else {}
        audio = AudioSettings(
            dialogue=self._empty_to_none(audio_data.get("dialogue")),
            dialogue_speaker=self._empty_to_none(audio_data.get("dialogue_speaker")),
            dialogue_tone=self._empty_to_none(audio_data.get("dialogue_tone")),
            sound_effects=audio_data.get("sound_effects", []),
            ambient_sounds=audio_data.get("ambient_sounds", []),
            background_music=self._empty_to_none(audio_data.get("background_music")),
            music_volume=audio_data.get("music_volume", "normal"),
        )

        # 技术参数
        tech_data = shot_data.get("technical", {})
        technical = TechnicalSettings(
            duration=min(max(tech_data.get("duration", 6.0), 2.0), 15.0),
            aspect_ratio=aspect_ratio,
            motion_speed=self._parse_enum(MotionSpeed, tech_data.get("motion_speed"), MotionSpeed.NORMAL),
            resolution="1080p",
            fps=24,
        )

        # 负面提示词
        neg_data = shot_data.get("negative", {})
        negative = NegativePrompt(
            avoid_elements=neg_data.get("avoid_elements", []),
            avoid_artifacts=neg_data.get("avoid_artifacts", True),
            avoid_text=neg_data.get("avoid_text", True),
        )

        return Shot(
            sequence=sequence,
            name=shot_data.get("name"),
            description_cn=shot_data.get("description_cn", ""),
            source_text=shot_data.get("source_text"),
            source_line_start=shot_data.get("source_line_start"),
            source_line_end=shot_data.get("source_line_end"),
            camera=camera,
            subject=subject,
            environment=environment,
            style=style,
            audio=audio,
            technical=technical,
            negative=negative,
            reference_images=[],
            start_frame=None,
            end_frame=None,
            transition_in=self._empty_to_none(shot_data.get("transition_in")),
            transition_out=self._empty_to_none(shot_data.get("transition_out")),
        )

    def _parse_enum(self, enum_class, value, default):
        """安全解析枚举值。"""
        if value is None or value == "":
            return default
        try:
            # 处理可能带空格的值
            clean_value = str(value).lower().replace(" ", "_").replace("-", "_")
            return enum_class(clean_value)
        except ValueError:
            return default

    def _empty_to_none(self, value: str | None) -> str | None:
        """将空字符串转换为 None。"""
        if value is None or value == "":
            return None
        return value

    def _resolve_asset_refs(
        self,
        asset_names: list[str],
        person_assets: list[dict],
        scene_assets: list[dict],
        item_assets: list[dict],
    ) -> list[UUID]:
        """根据资产名称解析资产ID。"""
        refs = []
        all_assets = person_assets + scene_assets + item_assets

        for name in asset_names:
            asset_id = self._find_asset_id(name, all_assets)
            if asset_id:
                refs.append(asset_id)

        return refs

    def _find_asset_id(self, name: str | None, assets: list[dict]) -> UUID | None:
        """根据名称查找资产ID。"""
        if not name:
            return None

        for asset in assets:
            if asset.get("canonical_name") == name:
                return UUID(asset["id"]) if isinstance(asset.get("id"), str) else asset.get("id")
            if name in asset.get("aliases", []):
                return UUID(asset["id"]) if isinstance(asset.get("id"), str) else asset.get("id")

        return None

    def build_platform_prompt(self, shot: Shot, platform: str = "veo") -> str:
        """为特定平台构建优化的提示词。

        Args:
            shot: 分镜对象
            platform: 目标平台 veo/vidu/kling/sora

        Returns:
            优化后的提示词
        """
        template = PLATFORM_PROMPT_TEMPLATES.get(platform)
        if not template:
            return shot.build_prompt(platform)

        # 构建音频相关字符串
        dialogue_prompt = ""
        if shot.audio.dialogue:
            speaker = shot.audio.dialogue_speaker or "Character"
            dialogue_prompt = f'{speaker} says: "{shot.audio.dialogue}"'

        sfx_prompt = ""
        if shot.audio.sound_effects:
            sfx_prompt = "SFX: " + ", ".join(shot.audio.sound_effects)

        ambient_prompt = ""
        if shot.audio.ambient_sounds:
            ambient_prompt = "Ambient: " + ", ".join(shot.audio.ambient_sounds)

        audio_prompt = ". ".join(filter(None, [dialogue_prompt, sfx_prompt, ambient_prompt]))

        # 格式化模板
        try:
            return template.format(
                shot_size=shot.camera.shot_size.value.replace("_", " "),
                camera_angle=shot.camera.camera_angle.value.replace("_", " "),
                camera_movement=shot.camera.camera_movement.value.replace("_", " "),
                lens_type=shot.camera.lens_type.value.replace("_", " "),
                subject_description=shot.subject.subject_description,
                action=shot.subject.action,
                emotion=shot.subject.emotion or "",
                location=shot.environment.location,
                time_of_day=shot.environment.time_of_day,
                lighting=shot.environment.lighting.value,
                lighting_details=shot.environment.lighting_details or "",
                atmosphere_elements=", ".join(shot.environment.atmosphere_elements),
                video_style=shot.style.video_style.value,
                mood=shot.style.mood.value,
                color_grading=shot.style.color_grading or "natural",
                dialogue_prompt=dialogue_prompt,
                sfx_prompt=sfx_prompt,
                ambient_prompt=ambient_prompt,
                audio_prompt=audio_prompt,
            )
        except KeyError:
            return shot.build_prompt(platform)


def create_storyboard_service(
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    model_name: str = "gpt-4o",
) -> StoryboardService:
    """创建分镜服务实例。

    Args:
        api_key: LLM API 密钥
        base_url: API 基础 URL
        model_name: 模型名称

    Returns:
        StoryboardService 实例
    """
    llm_client = OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )
    return StoryboardService(llm_client)
