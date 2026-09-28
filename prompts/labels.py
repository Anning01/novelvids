"""Stable legacy labels mapped to editable, language-specific display labels."""

from prompts.catalog import catalog

LABEL_KEYS = {
    "本镜头未引用已登记资产。": "no_registered_assets_are_referenced_in_this_shot",
    "保持当前可见状态": "maintain_the_current_visible_state",
    "无人物台词、旁白或人物内心 OS": "no_dialogue_narration_or_inner_monologue",
    "【核心生成指令｜高优先级】": "primary_generation_instructions_high_priority",
    "初始画面：": "initial_frame",
    "动作时间轴：": "action_timeline",
    "人声时间轴：": "voice_timeline",
    "同步声音：": "synchronized_sound",
    "【镜头": "shot",
    "【镜头1 · ": "shot_1",
    "】": "label_10",
    "时间范围：": "time_range",
    "运镜：": "camera_movement",
    "【旁白 / 内心 OS】": "narration_inner_monologue",
    "【人物台词】": "character_dialogue",
    "环境音：": "ambient_sound",
    "【详细执行】": "execution_details",
    "【禁止项】": "restrictions",
    "【风格定调】": "visual_style",
    "视觉风格：": "visual_style_19",
    "摄影规格：": "cinematography",
    "色彩基调：": "color_palette",
    "特效禁令：": "forbidden_effects",
    "【角色 / 道具 / 场景引用】": "character_prop_location_references",
    "【全局前置条件】": "global_conditions",
    "时间：": "time",
    "环境：": "environment",
    "空间关系：": "spatial_relationships",
    "【镜头描述】": "shot_description",
    "【转场方式】": "transition",
    "【特效规范】": "effects",
    "禁止：": "forbidden",
    "允许：": "allowed",
    "无特殊效果，纯自然光写实拍摄": "no_special_effects_realistic_natural_lighting",
    "无": "none",
    "总时长：": "total_duration",
    "角色": "characters",
    "角色描述": "character_description",
    "道具": "props",
    "道具描述": "prop_description",
    "场景": "locations",
    "场景描述": "location_description",
    "无字幕、无水印、无 LOGO、无 BGM，仅保留环境音效与人物台词。": "no_subtitles_watermarks_logos_or_background_music_use_only_ambient_sou",
    "无字幕、无水印、无 LOGO、无 BGM，仅保留环境音效、人物台词、旁白与人物内心 OS。": "no_subtitles_watermarks_logos_or_background_music_use_only_ambient_sou_43",
    "保留人物台词、环境音与背景音乐，声音层次清晰。": "keep_dialogue_ambience_and_background_music_clearly_separated",
    "无BGM，仅保留环境音效与人物台词。": "no_background_music_use_ambient_sound_and_dialogue_only",
    "【禁止项】\n无字幕、无水印、无LOGO。": "restrictions_no_subtitles_watermarks_or_logos",
    "按镜头动作与视线自然衔接。": "continue_naturally_from_the_shot_action_and_eyelines",
    "【转场方式】\n": "transition_48",
    "【背景音乐】\n": "background_music",
    "本片段无可复用的关键资产。": "no_reusable_key_assets_in_this_segment",
    "人物": "character",
    "角色参考": "character_references",
    "角色设定图": "character_design",
    "道具参考": "prop_references",
    "道具概念设计图": "prop_design",
    "场景参考": "location_references",
    "场景概念图": "location_design",
    "【声音设计】": "sound_design",
    "【当前请求资产定义】": "asset_definitions_for_this_request",
}

# Compatibility export; renderers select a complete locale catalog.
LABELS_EN = {
    source: catalog("labels.json", "en")[key] for source, key in LABEL_KEYS.items()
}


def prompt_label(source: str, language: str) -> str:
    key = LABEL_KEYS.get(source)
    return catalog("labels.json", language)[key] if key else source
