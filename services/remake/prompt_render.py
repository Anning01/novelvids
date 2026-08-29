"""重制工坊资产规范化与专业视频提示词渲染。"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from prompts.remake import SCENE_PROMPT_PREFIX, SINGLE_CHARACTER_PROMPT_PREFIX


def normalize_global_assets(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        "characters": _deduplicate_assets(raw.get("characters"), "character"),
        "scenes": _deduplicate_assets(raw.get("scenes"), "scene"),
        "objects": _deduplicate_assets(raw.get("objects"), "object"),
    }


def _deduplicate_assets(value: Any, prefix: str) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        key = _normalize(name)
        if not key:
            continue
        cleaned = {**item, "name": name}
        existing = unique.get(key)
        if existing is None or len(str(cleaned.get("description", ""))) > len(
            str(existing.get("description", ""))
        ):
            unique[key] = cleaned

    result: list[dict[str, Any]] = []
    for index, item in enumerate(unique.values(), start=1):
        core = str(item.get("description", "")).strip()
        label = str(item.get("label", "")).strip()
        if prefix == "character" and label in {"人物", "动物"}:
            description = f"{SINGLE_CHARACTER_PROMPT_PREFIX}\n\n角色描述：\n{core}"
        elif prefix == "scene":
            description = f"{SCENE_PROMPT_PREFIX}\n\n场景描述: {core}"
        elif prefix == "object":
            description = f"【道具描述】{core}"
        else:
            description = core
        result.append(
            {
                "id": f"{prefix}-{index:03d}",
                **item,
                "description": description,
            }
        )
    return result


def compact_catalog(assets: dict[str, Any]) -> list[dict[str, str]]:
    """仅传递视觉识别内容，不向场景模型重复资产图版式要求。"""
    result: list[dict[str, str]] = []
    for group_name, asset_type in (
        ("characters", "character"),
        ("scenes", "scene"),
        ("objects", "object"),
    ):
        for item in assets.get(group_name, []):
            if not isinstance(item, dict):
                continue
            result.append(
                {
                    "id": str(item.get("id", "")),
                    "type": asset_type,
                    "name": str(item.get("name", "")),
                    "label": str(item.get("label", "")),
                    "description": _asset_visual_content(item.get("description")),
                }
            )
    return result


def _asset_visual_content(value: Any) -> str:
    text = str(value or "").strip()
    for marker in ("角色描述：", "场景描述：", "场景描述:", "【道具描述】"):
        if marker in text:
            return text.split(marker, 1)[1].strip()
    return text


def _catalog_index(assets: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for group_name, asset_type in (
        ("characters", "character"),
        ("scenes", "scene"),
        ("objects", "object"),
    ):
        for item in assets.get(group_name, []):
            if isinstance(item, dict) and item.get("id"):
                result[str(item["id"])] = {**item, "asset_type": asset_type}
    return result


def render_professional_prompt(
    raw: dict[str, Any],
    assets: dict[str, Any],
    *,
    duration_seconds: float,
) -> dict[str, Any]:
    index = _catalog_index(assets)
    aligned_refs: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    mappings: list[tuple[str, str, str]] = []

    def add_reference(asset_id: str, model_name: str = "") -> dict[str, Any] | None:
        asset = index.get(asset_id)
        if not asset:
            return None
        canonical_name = str(asset["name"])
        mapping = (asset_id, model_name, canonical_name)
        if mapping not in mappings:
            mappings.append(mapping)
        if asset_id not in seen_ids:
            seen_ids.add(asset_id)
            aligned_refs.append(
                {
                    "asset_id": asset_id,
                    "asset_name": canonical_name,
                    "asset_type": str(asset["asset_type"]),
                }
            )
        return asset

    for reference in raw.get("asset_refs", []):
        if isinstance(reference, dict):
            add_reference(
                str(reference.get("asset_id", "")).strip(),
                str(reference.get("asset_name", "")).strip(),
            )
    for shot in raw.get("shots", []):
        if not isinstance(shot, dict):
            continue
        for dialogue in shot.get("dialogues", []):
            if isinstance(dialogue, dict):
                add_reference(
                    str(dialogue.get("speaker_asset_id", "")).strip(),
                    str(dialogue.get("speaker_name", "")).strip(),
                )

    raw_text = json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    for asset_id, asset in index.items():
        asset_name = str(asset.get("name", "")).strip()
        if asset_name and asset_name in raw_text:
            add_reference(asset_id, asset_name)

    style = raw.get("style") if isinstance(raw.get("style"), dict) else {}
    conditions = (
        raw.get("global_conditions")
        if isinstance(raw.get("global_conditions"), dict)
        else {}
    )
    audio = raw.get("audio") if isinstance(raw.get("audio"), dict) else {}
    effects = raw.get("effects") if isinstance(raw.get("effects"), dict) else {}
    audio_rule = (
        "保留人物台词、环境音与背景音乐，声音层次清晰。"
        if audio.get("has_bgm")
        else "无BGM，仅保留环境音效与人物台词。"
    )
    sections = [
        "【禁止项】\n无字幕、无水印、无LOGO。" + audio_rule,
        "\n".join(
            [
                "【风格定调】",
                f"视觉风格：{_align_text(style.get('visual_style'), mappings)}",
                f"摄影规格：{_align_text(style.get('cinematography'), mappings)}",
                f"色彩基调：{_align_text(style.get('color_tone'), mappings)}",
                f"特效禁令：{_align_text(effects.get('forbidden'), mappings)}",
            ]
        ),
        _reference_section(aligned_refs),
        "\n".join(
            [
                "【全局前置条件】",
                f"时间：{_align_text(conditions.get('time_weather'), mappings)}",
                f"环境：{_align_text(conditions.get('environment_light'), mappings)}",
                f"空间关系：{_align_text(conditions.get('spatial_relationships'), mappings)}",
            ]
        ),
    ]

    shot_lines = ["【镜头描述】"]
    raw_shots = [shot for shot in raw.get("shots", []) if isinstance(shot, dict)]
    raw_shots.sort(key=lambda shot: _int_value(shot.get("order"), 0))
    integer_timeline, integer_duration = _allocate_integer_timeline(
        raw_shots,
        duration_seconds,
    )
    for position, shot in enumerate(raw_shots):
        start, end = integer_timeline[position]
        order = _int_value(shot.get("order"), position + 1)
        shot_lines.append(
            f"【镜头{order} · {start}–{end}s · "
            f"{_align_text(shot.get('camera'), mappings)} · "
            f"{_align_text(shot.get('title'), mappings)}】"
        )
        description = _align_text(shot.get("description"), mappings)
        if description:
            shot_lines.append(description)
        environment_sound = _align_text(shot.get("environment_sound"), mappings)
        if environment_sound:
            shot_lines.append(f"环境音：{environment_sound}")
        for dialogue in shot.get("dialogues", []):
            if not isinstance(dialogue, dict):
                continue
            speaker_asset = index.get(str(dialogue.get("speaker_asset_id", "")).strip())
            speaker = (
                f"@{speaker_asset['name']}"
                if speaker_asset
                else str(dialogue.get("speaker_name", "人物")).strip()
            )
            delivery = str(dialogue.get("delivery", "")).strip()
            spoken_text = _clean_dialogue(dialogue.get("text"))
            shot_lines.append(f"{speaker}{delivery + '：' if delivery else '：'}「{spoken_text}」")
    sections.append("\n".join(shot_lines))
    sections.append(
        "【转场方式】\n"
        + (_align_text(raw.get("transition"), mappings) or "按镜头动作与视线自然衔接。")
    )
    sections.append(
        "\n".join(
            [
                "【特效规范】",
                f"禁止：{_align_text(effects.get('forbidden'), mappings)}",
                f"允许：{_align_text(effects.get('allowed'), mappings)}",
            ]
        )
    )
    if audio.get("has_bgm") and str(audio.get("bgm_description", "")).strip():
        sections.append("【背景音乐】\n" + str(audio["bgm_description"]).strip())
    sections.append(f"总时长：{integer_duration}s")
    prompt = _align_text("\n\n".join(sections), mappings)
    return {
        "shot_index": _int_value(raw.get("shot_index"), 0),
        "file": str(raw.get("file", "")),
        "duration_seconds": integer_duration,
        "asset_refs": aligned_refs,
        "prompt": prompt,
        "confidence": _float_value(raw.get("confidence")),
    }


def _reference_section(references: list[dict[str, str]]) -> str:
    labels = {"character": "角色", "object": "道具", "scene": "场景"}
    lines = ["【角色 / 道具 / 场景引用】"]
    grouped: dict[str, list[str]] = {asset_type: [] for asset_type in labels}
    for reference in references:
        asset_type = reference["asset_type"]
        if asset_type in grouped:
            grouped[asset_type].append(f"@{reference['asset_name']}")
    for asset_type in ("character", "object", "scene"):
        if grouped[asset_type]:
            lines.append(f"{labels[asset_type]}：{'、'.join(grouped[asset_type])}")
    if len(lines) == 1:
        lines.append("本片段无可复用的关键资产。")
    return "\n".join(lines)


def _align_text(value: Any, mappings: list[tuple[str, str, str]]) -> str:
    result = str(value or "").strip()
    grouped: dict[str, set[str]] = {}
    for asset_id, model_name, canonical_name in mappings:
        candidates = grouped.setdefault(canonical_name, set())
        candidates.update(
            candidate
            for candidate in (
                asset_id,
                f"【{model_name}】" if model_name else "",
                model_name,
                f"【{canonical_name}】",
                canonical_name,
            )
            if candidate
        )
    placeholders: dict[str, str] = {}
    for index, canonical_name in enumerate(sorted(grouped, key=len, reverse=True)):
        marker = f"@{canonical_name}"
        placeholder = f"\ue000asset-reference-{index}\ue001"
        placeholders[placeholder] = marker
        result = result.replace(marker, placeholder)
        for candidate in sorted(grouped[canonical_name], key=len, reverse=True):
            result = result.replace(candidate, placeholder)
    for placeholder, marker in placeholders.items():
        result = result.replace(placeholder, marker)
        escaped_marker = re.escape(marker)
        spacing = r"[ \t\u3000]*"
        result = re.sub(
            rf"{escaped_marker}(?:{spacing}[（(]{spacing}{escaped_marker}{spacing}[）)])+",
            marker,
            result,
        )
        result = re.sub(
            rf"(?:[（(]{spacing}{escaped_marker}{spacing}[）)]{spacing})+{escaped_marker}",
            marker,
            result,
        )
        result = re.sub(
            rf"{escaped_marker}(?:[ \t\u3000、，,]*{escaped_marker})+",
            marker,
            result,
        )
    return result


def _clean_dialogue(value: Any) -> str:
    text = str(value or "").strip()
    for left, right in (("{", "}"), ("“", "”"), ("「", "」"), ('"', '"')):
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            return text[len(left) : -len(right)].strip()
    return text


def _round_seconds(value: Any) -> int:
    return max(0, math.floor(_float_value(value) + 0.5))


def _allocate_integer_timeline(
    shots: list[dict[str, Any]],
    source_duration: float,
) -> tuple[list[tuple[int, int]], int]:
    total_seconds = max(1, _round_seconds(source_duration))
    if not shots:
        return [], total_seconds

    total_seconds = max(total_seconds, len(shots))
    weights: list[float] = []
    for position, shot in enumerate(shots):
        start = 0.0 if position == 0 else _float_value(shot.get("start_seconds"))
        end = (
            source_duration
            if position == len(shots) - 1 and source_duration > 0
            else _float_value(shot.get("end_seconds"))
        )
        weights.append(max(0.0, end - start))

    remaining = total_seconds - len(shots)
    weight_sum = sum(weights)
    quotas = (
        [remaining / len(shots)] * len(shots)
        if weight_sum <= 0
        else [remaining * weight / weight_sum for weight in weights]
    )
    extras = [math.floor(quota) for quota in quotas]
    leftover = remaining - sum(extras)
    remainder_order = sorted(
        range(len(shots)),
        key=lambda index: (quotas[index] - extras[index], weights[index]),
        reverse=True,
    )
    for index in remainder_order[:leftover]:
        extras[index] += 1

    timeline: list[tuple[int, int]] = []
    cursor = 0
    for extra in extras:
        end = cursor + 1 + extra
        timeline.append((cursor, end))
        cursor = end
    return timeline, total_seconds


def _normalize(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _int_value(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
