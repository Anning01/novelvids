"""Pure renderers for default asset image prompts stored in the database."""

from utils.prompt_language import normalize_prompt_language


CHARACTER_TURNAROUND = "character_turnaround"
GROUP_PORTRAIT = "group_portrait"
REFERENCE_OUTPUT_GUARD_ZH = "禁止生成任何文字、标签、Logo 或水印。"
REFERENCE_OUTPUT_GUARD_EN = "Do not output any text, labels, logos, or watermarks."

SINGLE_CHARACTER_PROMPT_PREFIX_ZH = (
    "任务：完成角色的上半身正面平视特写和该角色的全身三视图，"
    "左边是角色的上半身正面平视特写，右边是该角色的全身三视图。"
    "中性浅灰白色、无缝摄影棚背景、无环境元素、无墙角和地平线、仅保留浅接触阴影。"
    "三视图不可以有分割线，比例是16:9，左侧为角色胸部以上特写大图，占画面约 40% 宽度，"
    "用于展示面部、发型、表情、眼神、上半身服装和配饰细节，右侧为同一角色的三视图，"
    "占画面约 60% 宽度，依次展示正面全身、侧面全身、背面全身。"
    f"{REFERENCE_OUTPUT_GUARD_ZH}"
)

SCENE_PROMPT_PREFIX_ZH = (
    "生成四宫格画面，展示同一个场景中的四个不同视角。"
    "左上角为正视图，主体正面清晰可见，构图居中，细节完整；右上角为俯视图，"
    "从高空俯视整体空间布局，展示环境关系和场景结构；左下角为背视图，从主体后方观察，"
    "突出背部轮廓、空间纵深和环境延展；右下角为侧视图，从主体侧面观察，展示主体比例、"
    "层次和空间关系。四个画面保持同一场景、同一光照、同一色调、同一时间状态。"
    f"{REFERENCE_OUTPUT_GUARD_ZH}\n\n"
    "1. 只出现场景，不出现人物、道具等无关内容,\n"
    "2. 必须只展示静态事物，不能包含人，动物等可以自行运行的事物\n"
    "3. 无动态、特效、技能、光效及战斗相关描写。"
)

COMPLETE_REFERENCE_PROMPT_MARKERS = (
    "任务：完成角色的上半身正面平视特写",
    "任务：生成同一组角色的群像关系参考图",
    "生成四宫格画面，展示同一个场景",
    "【道具描述】",
    "Task: Create an upper-body, front-facing, eye-level close-up",
    "Task: Create an ensemble character relationship reference image",
    "Create a four-panel environment reference sheet",
    "[Prop description]",
)


def is_complete_reference_prompt(value: str) -> bool:
    """Return whether a value already contains an explicit image task."""
    text = value.strip()
    return any(text.startswith(marker) for marker in COMPLETE_REFERENCE_PROMPT_MARKERS)


def render_default_asset_prompt(
    *,
    asset_type: str,
    visual_traits: str,
    prompt_language: str = "en",
    aspect_ratio: str = "16:9",
    reference_layout: str = CHARACTER_TURNAROUND,
) -> str:
    """Render the editable default prompt that will be persisted with an asset.

    This renderer is intentionally used before persistence. Image generation must
    submit the stored prompt verbatim so a user's later edits remain authoritative.
    """
    details = visual_traits.strip()
    if not details or is_complete_reference_prompt(details):
        return details

    language = normalize_prompt_language(prompt_language)
    kind = asset_type.strip().lower()
    ratio = aspect_ratio.strip() or "16:9"
    layout = reference_layout.strip().lower()

    if kind == "person":
        if layout in {"group", "ensemble", "group_portrait", "group-portrait"}:
            return details
        if language == "zh":
            prefix = SINGLE_CHARACTER_PROMPT_PREFIX_ZH.replace(
                "比例是16:9",
                f"比例是{ratio}",
            )
            return f"{prefix}\n\n角色描述：\n{details}"
        return (
            "Task: Create an upper-body, front-facing, eye-level close-up of the character together with a "
            "full-body three-view turnaround. Place the upper-body close-up on the left and the full-body "
            "turnaround on the right. Use a seamless neutral light gray-white studio background with no "
            "environment, corners, or horizon line, retaining only soft contact shadows. "
            f"Use a {ratio} aspect ratio. The left close-up occupies about 40% of the canvas and clearly shows "
            "the face, hairstyle, expression, eyes, upper-body clothing, and accessories. The right side "
            "occupies about 60% and shows the same character in front, side, and back full-body views in that "
            "order. Identity, proportions, clothing, hairstyle, and accessories must remain exactly consistent "
            "across every view. Do not output borders or divider lines. "
            f"{REFERENCE_OUTPUT_GUARD_EN}\n\n"
            f"Character description:\n{details}"
        )

    if kind == "scene":
        if language == "zh":
            ratio_requirement = "" if ratio == "16:9" else f"\n4. 画面比例为 {ratio}。"
            return f"{SCENE_PROMPT_PREFIX_ZH}{ratio_requirement}\n\n场景描述: {details}"
        return (
            f"Create a four-panel environment reference sheet in a {ratio} aspect ratio, showing the same scene "
            "from four different viewpoints. Top-left: a centered front view with the main spatial subject "
            "clearly visible and complete. Top-right: a high-angle aerial view revealing the full layout, "
            "environmental relationships, and spatial structure. Bottom-left: a rear view emphasizing the back "
            "silhouette, depth, and continuation of the environment. Bottom-right: a side view showing scale, "
            "layers, and spatial relationships. All four panels must depict the exact same environment, "
            "architecture, set dressing, lighting, color palette, time of day, and weather state.\n\n"
            "Show only the environment. Do not include people, animals, hero props, or unrelated objects. "
            "Depict a static environment with no motion, effects, abilities, glowing effects, or combat. "
            f"{REFERENCE_OUTPUT_GUARD_EN}\n\n"
            f"Scene description:\n{details}"
        )

    if kind in {"item", "object", "prop"}:
        if language == "zh":
            return f"【道具描述】{details}\n\n{REFERENCE_OUTPUT_GUARD_ZH}"
        return f"[Prop description] {details}\n\n{REFERENCE_OUTPUT_GUARD_EN}"

    if language == "zh":
        return (
            f"生成画面比例为 {ratio} 的资产参考图。不输出文字、标签或水印。\n\n"
            f"资产描述：\n{details}"
        )
    return (
        f"Create an asset reference image in a {ratio} aspect ratio. Do not output text, labels, or "
        f"watermarks.\n\nAsset description:\n{details}"
    )
