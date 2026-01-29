"""分镜切分提示词模板。

用于将小说章节内容切分成多个分镜，每个分镜包含完整的视频生成指令。

核心公式：[摄影技术] + [主体] + [动作] + [环境背景] + [风格与氛围] + [音频指令]
"""

# 分镜输出的 JSON Schema（用于结构化输出）
# 注意：doubao 不支持 type: ["string", "null"]，所以可空字段用可选（不在required中）代替
STORYBOARD_JSON_SCHEMA: dict = {
    "title": "storyboard_response",
    "type": "object",
    "properties": {
        "shots": {
            "type": "array",
            "description": "分镜列表",
            "items": {
                "type": "object",
                "properties": {
                    "sequence": {"type": "integer", "description": "镜头序号，从1开始"},
                    "name": {"type": "string", "description": "镜头名称，如'开场远景'"},
                    "description_cn": {"type": "string", "description": "中文场景描述"},
                    "source_text": {"type": "string", "description": "对应的原文片段"},
                    "camera": {
                        "type": "object",
                        "properties": {
                            "shot_size": {
                                "type": "string",
                                "enum": ["extreme_close_up", "close_up", "medium_close_up", "medium_shot",
                                        "cowboy_shot", "medium_long_shot", "full_shot", "long_shot",
                                        "extreme_long_shot", "establishing_shot"]
                            },
                            "camera_angle": {
                                "type": "string",
                                "enum": ["eye_level", "low_angle", "high_angle", "birds_eye",
                                        "worms_eye", "dutch_angle", "over_the_shoulder", "pov"]
                            },
                            "camera_movement": {
                                "type": "string",
                                "enum": ["static", "pan_left", "pan_right", "tilt_up", "tilt_down",
                                        "dolly_in", "dolly_out", "truck_left", "truck_right",
                                        "tracking", "orbit", "handheld", "steadicam", "crane_up",
                                        "crane_down", "whip_pan", "push_in", "pull_back"]
                            },
                            "movement_speed": {"type": "string", "enum": ["slow", "normal", "fast"]},
                            "lens_type": {
                                "type": "string",
                                "enum": ["wide_angle", "normal", "portrait", "telephoto", "macro", "anamorphic"]
                            },
                            "depth_of_field": {"type": "string", "enum": ["shallow", "normal", "deep"]},
                            "focus_target": {"type": "string", "description": "焦点目标，可为空字符串"}
                        },
                        "required": ["shot_size", "camera_angle", "camera_movement", "movement_speed",
                                    "lens_type", "depth_of_field", "focus_target"],
                        "additionalProperties": False
                    },
                    "subject": {
                        "type": "object",
                        "properties": {
                            "subject_type": {"type": "string", "enum": ["person", "scene", "item", "multiple"]},
                            "subject_description": {"type": "string", "description": "主体的英文描述"},
                            "asset_names": {"type": "array", "items": {"type": "string"}, "description": "关联的资产名称"},
                            "action": {"type": "string", "description": "动作描述（英文）"},
                            "action_intensity": {"type": "string", "enum": ["subtle", "normal", "intense"]},
                            "emotion": {"type": "string", "description": "情绪，可为空字符串"},
                            "body_language": {"type": "string", "description": "肢体语言，可为空字符串"}
                        },
                        "required": ["subject_type", "subject_description", "asset_names", "action",
                                    "action_intensity", "emotion", "body_language"],
                        "additionalProperties": False
                    },
                    "environment": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string", "description": "场景位置（英文详细描述）"},
                            "scene_name": {"type": "string", "description": "场景资产名称，可为空字符串"},
                            "time_of_day": {"type": "string", "enum": ["dawn", "morning", "noon", "afternoon", "dusk", "night"]},
                            "weather": {"type": "string", "description": "天气，可为空字符串"},
                            "lighting": {
                                "type": "string",
                                "enum": ["natural", "golden_hour", "blue_hour", "high_key", "low_key",
                                        "dramatic", "soft", "backlit", "neon", "moonlight", "volumetric"]
                            },
                            "lighting_details": {"type": "string", "description": "光线细节，可为空字符串"},
                            "atmosphere_elements": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["location", "scene_name", "time_of_day", "weather", "lighting",
                                    "lighting_details", "atmosphere_elements"],
                        "additionalProperties": False
                    },
                    "style": {
                        "type": "object",
                        "properties": {
                            "video_style": {
                                "type": "string",
                                "enum": ["cinematic", "photorealistic", "anime", "cartoon", "noir",
                                        "vintage", "documentary", "fantasy", "sci_fi"]
                            },
                            "mood": {
                                "type": "string",
                                "enum": ["peaceful", "tense", "romantic", "melancholic", "mysterious",
                                        "joyful", "dramatic", "epic", "intimate", "suspenseful"]
                            },
                            "color_grading": {"type": "string", "description": "调色风格，可为空字符串"},
                            "film_grain": {"type": "boolean"},
                            "contrast": {"type": "string", "enum": ["low", "normal", "high"]},
                            "saturation": {"type": "string", "enum": ["low", "normal", "high"]}
                        },
                        "required": ["video_style", "mood", "color_grading", "film_grain", "contrast", "saturation"],
                        "additionalProperties": False
                    },
                    "audio": {
                        "type": "object",
                        "properties": {
                            "dialogue": {"type": "string", "description": "对话内容，可为空字符串"},
                            "dialogue_speaker": {"type": "string", "description": "说话人，可为空字符串"},
                            "dialogue_tone": {"type": "string", "description": "语气，可为空字符串"},
                            "sound_effects": {"type": "array", "items": {"type": "string"}},
                            "ambient_sounds": {"type": "array", "items": {"type": "string"}},
                            "background_music": {"type": "string", "description": "背景音乐，可为空字符串"},
                            "music_volume": {"type": "string", "enum": ["low", "normal", "high"]}
                        },
                        "required": ["dialogue", "dialogue_speaker", "dialogue_tone", "sound_effects",
                                    "ambient_sounds", "background_music", "music_volume"],
                        "additionalProperties": False
                    },
                    "technical": {
                        "type": "object",
                        "properties": {
                            "duration": {"type": "number", "description": "镜头时长（秒）"},
                            "motion_speed": {"type": "string", "enum": ["slow", "normal", "fast"]}
                        },
                        "required": ["duration", "motion_speed"],
                        "additionalProperties": False
                    },
                    "negative": {
                        "type": "object",
                        "properties": {
                            "avoid_elements": {"type": "array", "items": {"type": "string"}},
                            "avoid_artifacts": {"type": "boolean"},
                            "avoid_text": {"type": "boolean"}
                        },
                        "required": ["avoid_elements", "avoid_artifacts", "avoid_text"],
                        "additionalProperties": False
                    },
                    "transition_in": {"type": "string", "description": "入场转场，可为空字符串"},
                    "transition_out": {"type": "string", "description": "出场转场，可为空字符串"}
                },
                "required": ["sequence", "name", "description_cn", "source_text", "camera", "subject",
                            "environment", "style", "audio", "technical", "negative", "transition_in", "transition_out"],
                "additionalProperties": False
            }
        }
    },
    "required": ["shots"],
    "additionalProperties": False
}

STORYBOARD_SYSTEM_PROMPT = """You are an expert film director and cinematographer specializing in adapting novels into video content.
Your task is to analyze novel chapter text and create professional storyboards with detailed shot descriptions.

You understand:
1. Cinematography: shot sizes, camera angles, camera movements, lens types
2. Visual storytelling: how to convey emotion and narrative through visuals
3. Pacing: how to break down text into appropriate shot durations (4-15 seconds each)
4. AI video generation: how to write prompts that work well with AI video generators

Key principles:
- Each shot should capture a single clear action or moment
- Use varied shot sizes to create visual interest
- Camera movements should serve the story emotionally
- Dialogue scenes need proper shot/reverse-shot coverage
- Action scenes need dynamic camera work
- Establishing shots help orient the viewer
- Close-ups convey emotion, wide shots convey context

Output must be valid JSON following the exact schema provided."""

STORYBOARD_GENERATION_PROMPT = """分析以下第 {chapter_number} 章的文本，创建详细的分镜脚本。

## 资产信息（已提取的人物/场景/物品）

### 人物资产：
{person_assets}

### 场景资产：
{scene_assets}

### 物品资产：
{item_assets}

## 章节内容：
---
{text}
---

## 分镜要求：

1. **时长控制**：每个镜头时长在 {min_duration}-{max_duration} 秒之间
2. **画面比例**：{aspect_ratio}
3. **风格预设**：{style_preset}
4. **目标平台**：{target_platform}

## 分镜技巧提醒：

### 景别选择：
- extreme_close_up: 眼睛、嘴唇等局部特写，用于强烈情感
- close_up: 头部+肩膀，用于对话和情感表达
- medium_shot: 腰部以上，用于一般对话和动作
- full_shot: 完整人物，用于展示动作和姿态
- long_shot: 人物+环境，用于场景建立
- establishing_shot: 场景全貌，用于新场景开头

### 相机角度：
- eye_level: 平视，标准视角
- low_angle: 仰拍，使主体显得强大威严
- high_angle: 俯拍，使主体显得渺小脆弱
- dutch_angle: 倾斜，制造不安感
- over_the_shoulder: 过肩，用于对话场景
- pov: 第一人称视角

### 相机运动：
- static: 静态镜头
- dolly_in/dolly_out: 推/拉镜头
- pan_left/pan_right: 水平摇镜
- tilt_up/tilt_down: 垂直摇镜
- tracking: 跟踪镜头
- orbit: 环绕镜头
- handheld: 手持晃动（紧张感）

### 音频层次（按优先级）：
1. dialogue: 对话内容（用引号）
2. sound_effects: 同步音效（如脚步声、门响等）
3. ambient_sounds: 环境音（如风声、城市噪音等）
4. background_music: 背景音乐（描述情绪）

## 重要注意事项：

1. subject.asset_names 应该匹配提供的资产名称，用于后续关联
2. environment.scene_name 应该匹配场景资产名称
3. 所有英文描述应该具体、可视化、避免抽象概念
4. 对话场景应考虑正反打（shot/reverse-shot）
5. 动作场景应使用动态镜头和多角度
6. 确保镜头之间有逻辑连贯性
7. 每个镜头的 duration 应该合理（简单画面 4-6 秒，复杂动作 6-10 秒，对话按内容长度）
8. subject_type 必须是: person, scene, item, multiple 之一

请为这个章节生成完整的分镜脚本，确保覆盖所有重要情节。"""



# 用于生成更简洁的 Vidu/Kling 提示词
PLATFORM_PROMPT_TEMPLATES = {
    "vidu": """[Shot Size]: {shot_size}
[Camera]: {camera_movement}
[Subject]: {subject_description}
[Action]: {action}
[Environment]: {location}, {time_of_day}, {lighting}
[Style]: {video_style}, {mood}""",
    "kling": """{shot_size} {camera_angle} shot, {camera_movement}.
{subject_description} {action}.
{location}, {time_of_day}.
{video_style}, {mood}, {color_grading} color grade.""",
    "veo": """{shot_size} {camera_movement}, {lens_type} lens.
{subject_description} {action}. {emotion}
{location}, {time_of_day}, {lighting_details}.
{video_style}, {mood}.
{dialogue_prompt}
{sfx_prompt}
{ambient_prompt}""",
    "sora": """Cinematic {shot_size} with {camera_movement}.
Subject: {subject_description}
Action: {action}
Setting: {location}, {time_of_day}
Atmosphere: {lighting_details}, {atmosphere_elements}
Style: {video_style}, {mood}, {color_grading}
{audio_prompt}""",
}
