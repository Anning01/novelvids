"""Resolve project voice selections into provider-compatible audio references."""

from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import settings
from models.audio_reference import AudioReference
from models.asset_variant import AssetVariant
from models.novel import Novel
from models.scene import Scene
from services.audio_references import audio_reference_accessible
from services.oss import make_upload_key, oss, resolve_media_url
from services.video.capabilities import VideoModelCapabilities
from utils.enums import AssetTypeEnum


@dataclass(frozen=True)
class ResolvedVoiceReference:
    reference_id: int
    nickname: str
    kind: str
    subjects: tuple[str, ...]
    url: str
    source: str
    duration: float | None


def _positive_reference_id(value: Any) -> int | None:
    try:
        reference_id = int(value)
    except (TypeError, ValueError):
        return None
    return reference_id if reference_id > 0 else None


def _has_narrator(scene: Scene) -> bool:
    params = scene.prompt_params if isinstance(scene.prompt_params, dict) else {}
    tracks = params.get("narration")
    if isinstance(tracks, list):
        return any(isinstance(line, str) and "旁白" in line for line in tracks)
    return "旁白（" in (scene.prompt or "") or "旁白：" in (scene.prompt or "")


def _character_has_dialogue(scene: Scene, names: list[str]) -> bool:
    params = scene.prompt_params if isinstance(scene.prompt_params, dict) else {}
    narration = params.get("narration")
    narration_lines = narration if isinstance(narration, list) else []
    text = "\n".join([
        scene.prompt or "",
        *(line for line in narration_lines if isinstance(line, str)),
    ])
    for name in names:
        escaped = re.escape(name)
        if re.search(rf"(?:@\{{?{escaped}\}}?|{escaped})\s*(?:[（(][^\n）)]*[）)])?\s*[:：]", text):
            return True
    return False


def _local_audio_path(url: str) -> Path:
    relative = Path(url.removeprefix("/media/")).as_posix()
    media_root = Path(settings.MEDIA_PATH).resolve()
    path = (media_root / relative).resolve()
    if media_root not in path.parents or not path.is_file():
        raise HTTPException(400, detail="本地参考音频不存在")
    return path


def _audio_data_uri(path: Path) -> str:
    extension = path.suffix.lower().lstrip(".")
    if extension not in {"mp3", "wav"}:
        raise HTTPException(400, detail="本地参考音频仅支持 MP3 或 WAV")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:audio/{extension};base64,{encoded}"


async def _provider_audio_url(
    reference: AudioReference,
    capabilities: VideoModelCapabilities,
    *,
    team_id: int | None,
) -> str:
    if reference.source == "system" and capabilities.system_audio_asset_scheme:
        return f"{capabilities.system_audio_asset_scheme}{reference.asset_id}"
    url = resolve_media_url(reference.audio_url) or reference.audio_url
    if url.startswith("/media/"):
        if not capabilities.supports_audio_data_uri:
            if not oss.enabled and capabilities.supports_temporary_file_upload:
                # Wan 3 适配器会在提交前把该本地 data URI 上传到百炼临时存储，
                # 再以模型绑定的 oss:// URL 调用，不会把 Base64 直接交给模型。
                return await asyncio.to_thread(_audio_data_uri, _local_audio_path(url))
            if not oss.enabled:
                raise HTTPException(
                    400,
                    detail=f"当前模型不支持本地音频 Base64，请启用 OSS 或为音色“{reference.nickname}”提供公网 URL",
                )
            path = _local_audio_path(url)
            extension = path.suffix.lower()
            content_type = "audio/mpeg" if extension == ".mp3" else "audio/wav"
            key = make_upload_key(team_id, path.name)
            # OSS Provider 的 put_file 使用服务端内网 endpoint；只把公网 URL 交给模型。
            await oss.put_file(key, path, content_type)
            reference.audio_url = key
            update_fields = ["audio_url", "updated_at"]
            if reference.team_id is None and team_id is not None:
                reference.team_id = team_id
                update_fields.append("team_id")
            await reference.save(update_fields=update_fields)
            return resolve_media_url(key) or key
        return await asyncio.to_thread(_audio_data_uri, _local_audio_path(url))
    if url.startswith("data:audio/") and not capabilities.supports_audio_data_uri:
        if capabilities.supports_temporary_file_upload:
            return url
        raise HTTPException(400, detail="当前模型的参考音频仅支持公网 URL")
    if not url.startswith(("http://", "https://", "data:audio/")):
        raise HTTPException(400, detail=f"音色“{reference.nickname}”没有可用的公网 URL")
    return url


async def resolve_voice_references(
    *,
    scene: Scene,
    novel: Novel,
    subjects: list[dict[str, Any]],
    capabilities: VideoModelCapabilities,
) -> list[ResolvedVoiceReference]:
    """Resolve only voices actually used by this shot, deduplicated by audio asset."""
    assignments: list[tuple[int, str, str]] = []
    narrator_id = _positive_reference_id(novel.narrator_audio_reference_id)
    if narrator_id and _has_narrator(scene):
        assignments.append((narrator_id, "narrator", "旁白"))
    scene_assets = {
        asset.canonical_name: asset
        for asset in await scene.assets.all()
    }
    metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
    raw_variant_ids = metadata.get("asset_variant_ids")
    variant_ids = raw_variant_ids if isinstance(raw_variant_ids, dict) else {}
    selected_variant_ids = {
        asset.id: _positive_reference_id(variant_ids.get(str(asset.id), variant_ids.get(asset.id)))
        for asset in scene_assets.values()
    }
    requested_variant_ids = [value for value in selected_variant_ids.values() if value]
    variants = {
        variant.id: variant
        for variant in await AssetVariant.filter(id__in=requested_variant_ids)
    } if requested_variant_ids else {}

    def asset_voice_reference_id(asset: Any) -> int | None:
        asset_metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
        reference_id = _positive_reference_id(asset_metadata.get("voice_reference_id"))
        variant_id = selected_variant_ids.get(asset.id)
        variant = variants.get(variant_id) if variant_id else None
        if variant is not None and isinstance(variant.metadata, dict):
            reference_id = (
                _positive_reference_id(variant.metadata.get("voice_reference_id"))
                or reference_id
            )
        return reference_id

    assigned_names: set[str] = set()
    for subject in subjects:
        name = str(subject.get("name") or "").partition("#")[0]
        asset = scene_assets.get(name)
        reference_id = _positive_reference_id(subject.get("voice_reference_id"))
        if asset is not None:
            reference_id = asset_voice_reference_id(asset)
        if reference_id and name:
            assignments.append((reference_id, "character", name))
            assigned_names.add(name)
    for asset in scene_assets.values():
        name = asset.canonical_name
        if name in assigned_names or asset.asset_type != AssetTypeEnum.person.value:
            continue
        aliases = asset.aliases if isinstance(asset.aliases, list) else []
        if not _character_has_dialogue(scene, [name, *aliases]):
            continue
        reference_id = asset_voice_reference_id(asset)
        if reference_id:
            assignments.append((reference_id, "character", name))
    if not assignments:
        return []

    reference_ids = list(dict.fromkeys(item[0] for item in assignments))
    rows = await AudioReference.filter(id__in=reference_ids, is_active=True)
    references = {
        row.id: row
        for row in rows
        if audio_reference_accessible(
            row,
            team_id=novel.team_id,
            created_by=novel.created_by,
        )
    }
    missing = [reference_id for reference_id in reference_ids if reference_id not in references]
    if missing:
        raise HTTPException(400, detail="分镜使用的角色或旁白音色不存在，请重新选择")

    grouped: dict[int, tuple[str, list[str]]] = {}
    for reference_id, kind, subject in assignments:
        current = grouped.get(reference_id)
        if current is None:
            grouped[reference_id] = (kind, [subject])
        elif subject not in current[1]:
            current[1].append(subject)
    if len(grouped) > capabilities.max_reference_audios:
        raise HTTPException(
            400,
            detail=f"当前模型单个镜头最多使用 {capabilities.max_reference_audios} 个不同音色，请合并或减少说话角色",
        )

    known_total_duration = 0.0
    for reference_id in grouped:
        reference = references[reference_id]
        if reference.duration is None:
            continue
        duration = float(reference.duration)
        if not capabilities.reference_audio_duration_min <= duration <= capabilities.reference_audio_duration_max:
            raise HTTPException(
                400,
                detail=(
                    f"音色“{reference.nickname}”时长为 {duration:g} 秒，当前模型要求单段参考音频为 "
                    f"{capabilities.reference_audio_duration_min}-{capabilities.reference_audio_duration_max} 秒"
                ),
            )
        known_total_duration += duration
    if known_total_duration > capabilities.reference_audio_total_duration_max + 0.001:
        raise HTTPException(
            400,
            detail=(
                f"当前镜头参考音频总时长为 {known_total_duration:g} 秒，当前模型最多允许 "
                f"{capabilities.reference_audio_total_duration_max} 秒"
            ),
        )

    resolved: list[ResolvedVoiceReference] = []
    for reference_id, (kind, names) in grouped.items():
        reference = references[reference_id]
        resolved.append(ResolvedVoiceReference(
            reference_id=reference.id,
            nickname=reference.nickname,
            kind=kind,
            subjects=tuple(names),
            url=await _provider_audio_url(
                reference,
                capabilities,
                team_id=novel.team_id,
            ),
            source=reference.source,
            duration=reference.duration,
        ))
    return resolved
