from typing import Any

from services.image_generation import generate_images
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _reference_layout(data: dict[str, Any]) -> str:
    metadata = data.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    workbench = metadata.get("workbench")
    workbench = workbench if isinstance(workbench, dict) else {}
    layout = _text(
        data.get("reference_layout")
        or metadata.get("reference_layout")
        or metadata.get("referenceLayout")
        or workbench.get("referenceLayout")
    ).lower()
    if layout in {"group", "ensemble", "group_portrait", "group-portrait"}:
        return GROUP_PORTRAIT
    return CHARACTER_TURNAROUND


def _details(data: dict[str, Any]) -> str:
    """Return visual identity only; narrative description is not an image prompt."""
    return _text(data.get("base_traits"))


def _is_complete_reference_prompt(value: str) -> bool:
    markers = (
        "任务：完成角色的上半身正面平视特写",
        "任务：生成同一组角色的群像关系参考图",
        "生成四宫格画面，展示同一个场景",
        "【道具描述】",
        "Task: Create an upper-body, front-facing, eye-level close-up",
        "Task: Create an ensemble character relationship reference image",
        "Create a four-panel environment reference sheet",
        "[Prop description]",
    )
    return any(value.startswith(marker) for marker in markers)


def _character_prompt(data: dict[str, Any], language: str, ratio: str) -> str:
    details = _details(data)
    if _reference_layout(data) == GROUP_PORTRAIT:
        # shengshimedia keeps the model-produced 15-field ensemble description
        # verbatim instead of forcing the single-character turnaround layout.
        return details

    if language == "zh":
        prefix = SINGLE_CHARACTER_PROMPT_PREFIX_ZH.replace("比例是16:9", f"比例是{ratio}")
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


def _scene_prompt(data: dict[str, Any], language: str, ratio: str) -> str:
    details = _details(data)
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


def _item_prompt(data: dict[str, Any], language: str, ratio: str) -> str:
    details = _details(data)
    if language == "zh":
        return f"【道具描述】{details}\n\n{REFERENCE_OUTPUT_GUARD_ZH}"
    return f"[Prop description] {details}\n\n{REFERENCE_OUTPUT_GUARD_EN}"


def build_sora_compatible_prompt(data: dict[str, Any], prompt_language: str = "en") -> str:
    """Build a stable reference-sheet prompt in the configured language."""
    language = normalize_prompt_language(prompt_language)
    asset_type = _text(data.get("type")).lower()
    ratio = _text(data.get("aspect_ratio")) or "16:9"
    supplied_prompt = _text(data.get("base_traits"))

    if _is_complete_reference_prompt(supplied_prompt):
        return supplied_prompt

    if asset_type == "person":
        return _character_prompt(data, language, ratio)
    if asset_type == "scene":
        return _scene_prompt(data, language, ratio)
    if asset_type in {"item", "object", "prop"}:
        return _item_prompt(data, language, ratio)

    details = _details(data)
    if language == "zh":
        return f"生成画面比例为 {ratio} 的资产参考图。不输出文字、标签或水印。\n\n资产描述：\n{details}"
    return (
        f"Create an asset reference image in a {ratio} aspect ratio. Do not output text, labels, or "
        f"watermarks.\n\nAsset description:\n{details}"
    )


async def generate_for_sora_consistency(
    data,
    *,
    base_url,
    api_key,
    api_protocol="openai_compatible",
    reference_images=None,
    model="doubao-seedream-4-5-251128",
    resolution="2K",
    aspect_ratio="16:9",
    count=1,
    output_format="png",
    quality=None,
    prompt_language="en",
):
    """Execute a reference-image generation task with optional image references."""
    final_prompt = build_sora_compatible_prompt(
        {**data, "aspect_ratio": aspect_ratio},
        prompt_language,
    )

    extra_body = {}

    if reference_images:
        extra_body["image"] = reference_images

    try:
        result = []
        for _ in range(max(1, int(count))):
            result.extend(await generate_images(
                base_url=base_url,
                api_key=api_key,
                model=model,
                prompt=final_prompt,
                api_protocol=api_protocol,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                count=1,
                output_format=output_format,
                quality=quality,
                extra_body=extra_body,
            ))
        return result
    except Exception as error:
        print(f"生成异常: {error}")
        raise
