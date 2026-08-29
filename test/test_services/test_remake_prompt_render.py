from prompts.remake import (
    ASSET_PROMPT,
    ASSET_SCHEMA,
    PROMPT_TEMPLATE,
    SCENE_PROMPT_PREFIX,
    SINGLE_CHARACTER_PROMPT_PREFIX,
)
from pathlib import Path
from services.remake.prompt_render import (
    compact_catalog,
    normalize_global_assets,
    render_professional_prompt,
)


def test_asset_prompt_contract_matches_reference_pipeline():
    character = ASSET_SCHEMA["properties"]["characters"]["items"]

    assert character["properties"]["label"]["enum"] == ["人物", "动物", "群像"]
    assert character["required"] == ["name", "label", "description"]
    assert "先在内部判断出现次数" in ASSET_PROMPT
    assert "不输出次数和判断过程" in ASSET_PROMPT


def test_storyboard_prompt_requires_subtitle_review_before_unclear_marker():
    assert "不得在第一次听觉识别失败后停止" in PROMPT_TEMPLATE
    assert "必须用字幕补足听不清的内容" in PROMPT_TEMPLATE
    assert "不得用“[听不清]”“无法识别”" in PROMPT_TEMPLATE
    assert "对应时间段没有任何清晰可读的对白字幕" in PROMPT_TEMPLATE
    assert "对每一处“[听不清]”重新检查对应画面字幕" in PROMPT_TEMPLATE
    assert "听不清处标记“[听不清]”" not in PROMPT_TEMPLATE


def test_global_assets_are_deduplicated_and_receive_stable_reference_layouts():
    assets = normalize_global_assets(
        {
            "characters": [
                {"name": "将军", "label": "人物", "description": "黑色铠甲，红色盔缨"},
                {"name": "将军", "label": "人物", "description": "短描述"},
                {"name": "守卫群体", "label": "群像", "description": "统一札甲的守卫"},
            ],
            "scenes": [{"name": "军帐", "description": "深色军帐"}],
            "objects": [{"name": "令牌", "description": "黑色木质令牌"}],
        }
    )

    assert len(assets["characters"]) == 2
    assert assets["characters"][0]["id"] == "character-001"
    assert assets["characters"][0]["description"] == (
        f"{SINGLE_CHARACTER_PROMPT_PREFIX}\n\n角色描述：\n黑色铠甲，红色盔缨"
    )
    assert assets["characters"][1]["description"] == "统一札甲的守卫"
    assert assets["scenes"][0]["description"] == (
        f"{SCENE_PROMPT_PREFIX}\n\n场景描述: 深色军帐"
    )
    assert assets["objects"][0]["description"] == "【道具描述】黑色木质令牌"


def test_compact_catalog_strips_reference_image_layout_instructions():
    catalog = compact_catalog(
        {
            "characters": [{"id": "character-001", "name": "将军", "label": "人物", "description": "三视图\n\n角色描述：\n黑色铠甲"}],
            "scenes": [{"id": "scene-001", "name": "军帐", "description": "四宫格\n\n场景描述: 深色军帐"}],
            "objects": [],
        }
    )

    assert catalog[0]["description"] == "黑色铠甲"
    assert catalog[1]["description"] == "深色军帐"


def test_professional_prompt_keeps_only_known_asset_refs_and_integer_timeline():
    assets = {
        "characters": [{"id": "character-001", "name": "将军", "label": "人物", "description": "黑甲"}],
        "scenes": [],
        "objects": [],
    }
    result = render_professional_prompt(
        {
            "shot_index": 1,
            "file": "scene-001.mp4",
            "asset_refs": [
                {"asset_id": "character-001", "asset_name": "黑甲男人", "asset_type": "character"},
                {"asset_id": "unknown", "asset_name": "不存在", "asset_type": "object"},
            ],
            "style": {"visual_style": "写实古装", "cinematography": "24fps", "color_tone": "暖色"},
            "global_conditions": {"time_weather": "夜", "environment_light": "烛火", "spatial_relationships": "将军在中央"},
            "audio": {"has_bgm": False, "bgm_description": ""},
            "shots": [
                {"order": 1, "start_seconds": 0, "end_seconds": 0.3, "title": "叠化", "camera": "固定", "description": "character-001 端坐", "environment_sound": "风声", "dialogues": []},
                {"order": 2, "start_seconds": 0.3, "end_seconds": 5.133, "title": "抬眼", "camera": "推进", "description": "将军抬眼", "environment_sound": "", "dialogues": []},
            ],
            "transition": "硬切",
            "effects": {"forbidden": "禁止变形", "allowed": "自然景深"},
            "confidence": 0.9,
        },
        assets,
        duration_seconds=5.133,
    )

    assert result["duration_seconds"] == 5
    assert result["asset_refs"] == [{"asset_id": "character-001", "asset_name": "将军", "asset_type": "character"}]
    assert "unknown" not in result["prompt"]
    assert "【镜头1 · 0–1s" in result["prompt"]
    assert "【镜头2 · 1–5s" in result["prompt"]
    assert "@将军 端坐" in result["prompt"]
    assert "总时长：5s" in result["prompt"]


def test_remake_services_do_not_inline_large_prompt_contracts():
    service_root = Path(__file__).parents[2] / "services" / "remake"
    service_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in service_root.glob("*.py")
    )

    assert "先在内部判断出现次数" not in service_text
    assert "你是专业影视导演和视频生成提示词逆向工程师" not in service_text
