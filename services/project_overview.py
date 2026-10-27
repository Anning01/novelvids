"""Batch-read project progress without loading manuscripts or estimating runtime."""

from collections import defaultdict
import math

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.chapter import Chapter
from models.novel import Novel
from models.scene import Scene
from models.video import Video
from schemas.project_overview import (
    ProjectOverview, ProjectOverviewItem, ProjectOverviewSummary, ProjectProduction,
)
from services.oss import normalize_media_url
from services.audio_references import audio_reference_accessible


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _reference_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    try:
        number = int(value)
    except (ValueError, TypeError):
        return None
    return number if number > 0 else None


def _reported_seconds(video):
    accounting = _mapping(_mapping(video["metadata"]).get("provider_accounting"))
    if accounting.get("usage_reported") is not True:
        return None
    value = accounting.get("reported_seconds", accounting.get("seconds"))
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


async def project_overview(team_id: int | None = None) -> ProjectOverview:
    projects = await Novel.filter(**({"team_id": team_id} if team_id is not None else {})).values(
        "id", "name", "author", "description", "cover", "total_chapters", "workflow_kind",
        "aspect_ratio", "resolution", "tags", "project_type", "created_at", "updated_at",
        "narrator_audio_reference_id",
        "team_id", "created_by",
    )
    if not projects:
        return ProjectOverview(items=[], summary=ProjectOverviewSummary())
    ids = [project["id"] for project in projects]
    chapters = await Chapter.filter(novel_id__in=ids).values("id", "novel_id", "number", "updated_at")
    assets = await Asset.filter(novel_id__in=ids).values(
        "id", "novel_id", "main_image", "angle_image_1", "angle_image_2", "metadata", "updated_at",
    )
    # Scope through active parents as well, so archived assets cannot contribute variants.
    variants = await AssetVariant.filter(asset_id__in=[asset["id"] for asset in assets]).values(
        "asset_id", "images", "metadata", "updated_at",
    )
    scenes = await Scene.filter(chapter_id__in=[chapter["id"] for chapter in chapters]).values(
        "id", "chapter_id", "metadata", "updated_at",
    )
    videos = await Video.filter(scene_id__in=[scene["id"] for scene in scenes]).order_by("-id").values(
        "id", "scene_id", "status", "url", "metadata", "updated_at",
    )
    media = {project["id"]: set() for project in projects}
    voice_ids = defaultdict(set)
    metrics = {
        project["id"]: ProjectProduction(latest_activity_at=project["updated_at"])
        for project in projects
    }
    project_by_id = {project["id"]: project for project in projects}
    latest_completion = {}

    def add_media(project_id, value):
        if isinstance(value, str) and value.strip():
            if reference := normalize_media_url(value.strip()):
                media[project_id].add(reference)

    def add_voice(project_id, value):
        if reference_id := _reference_id(value):
            voice_ids[project_id].add(reference_id)

    def touch(project_id, value):
        metrics[project_id].latest_activity_at = max(metrics[project_id].latest_activity_at, value)

    asset_projects = {asset["id"]: asset["novel_id"] for asset in assets}
    for project in projects:
        add_voice(project["id"], project["narrator_audio_reference_id"])
    for asset in assets:
        project_id = asset["novel_id"]
        for field in ("main_image", "angle_image_1", "angle_image_2"):
            add_media(project_id, asset[field])
        add_voice(project_id, _mapping(asset["metadata"]).get("voice_reference_id"))
        touch(project_id, asset["updated_at"])
    for variant in variants:
        project_id = asset_projects[variant["asset_id"]]
        for image in variant["images"] if isinstance(variant["images"], list) else []:
            add_media(project_id, image)
        add_voice(project_id, _mapping(variant["metadata"]).get("voice_reference_id"))
        touch(project_id, variant["updated_at"])
    voice_projects = defaultdict(set)
    for project_id, references in voice_ids.items():
        for value in references:
            if (reference_id := _reference_id(value)) is not None:
                voice_projects[reference_id].add(project_id)
    voices = await AudioReference.filter(id__in=list(voice_projects), is_active=True)
    for voice in voices:
        for project_id in voice_projects[voice.id]:
            project = project_by_id[project_id]
            if audio_reference_accessible(voice, team_id=project["team_id"], created_by=project["created_by"]):
                add_media(project_id, voice.audio_url)

    scenes_by_chapter = defaultdict(list)
    videos_by_scene = defaultdict(list)
    for scene in scenes:
        scenes_by_chapter[scene["chapter_id"]].append(scene)
    for video in videos:
        videos_by_scene[video["scene_id"]].append(video)
    chapter_projects = {chapter["id"]: chapter["novel_id"] for chapter in chapters}
    for scene in scenes:
        for video in videos_by_scene[scene["id"]]:
            touch(chapter_projects[scene["chapter_id"]], video["updated_at"])
    for chapter in chapters:
        project_id = chapter["novel_id"]
        metric = metrics[project_id]
        metric.chapter_count += 1
        touch(project_id, chapter["updated_at"])
        shots = scenes_by_chapter[chapter["id"]]
        metric.shot_count += len(shots)
        metric.storyboard_chapter_count += bool(shots)
        completed = 0
        completed_at = None
        for scene in shots:
            touch(project_id, scene["updated_at"])
            metadata = _mapping(scene["metadata"])
            references = metadata.get("video_reference_media")
            for reference in references if isinstance(references, list) else []:
                if isinstance(reference, dict) and reference.get("type") in {"image", "video"}:
                    add_media(project_id, reference.get("url"))
            active_id = _reference_id(metadata.get("current_video_id") or _mapping(metadata.get("workbench")).get("activeVideoId"))
            selected = next((video for video in videos_by_scene[scene["id"]]
                if video["status"] == 3 and video["url"]
                and (active_id is None or video["id"] == active_id)), None)
            if selected is None:
                continue
            completed += 1
            completed_at = max(completed_at, selected["updated_at"]) if completed_at else selected["updated_at"]
            metric.completed_shot_count += 1
            add_media(project_id, selected["url"])
            seconds = _reported_seconds(selected)
            if seconds is None:
                metric.unknown_duration_count += 1
            else:
                metric.video_seconds += seconds
            touch(project_id, selected["updated_at"])
        if shots and completed == len(shots):
            metric.completed_episode_count += 1
            if project_id not in latest_completion or completed_at > latest_completion[project_id]:
                latest_completion[project_id] = completed_at
                metric.latest_episode_number = chapter["number"]
    items = []
    for project in projects:
        metric = metrics[project["id"]]
        metric.asset_count = len(media[project["id"]])
        metric.video_seconds = round(metric.video_seconds, 3)
        metric.state = "ready" if metric.completed_episode_count else "in_progress" if metric.shot_count or metric.asset_count else "not_started"
        items.append(ProjectOverviewItem.model_validate({
            **project, "tags": project["tags"] or [], "production": metric,
        }))
    items.sort(key=lambda item: (item.production.latest_activity_at, item.id), reverse=True)
    return ProjectOverview(items=items, summary=ProjectOverviewSummary(
        project_count=len(items), chapter_count=sum(item.production.chapter_count for item in items),
        asset_count=sum(item.production.asset_count for item in items),
        video_seconds=round(sum(item.production.video_seconds for item in items), 3),
        unknown_duration_count=sum(item.production.unknown_duration_count for item in items),
    ))
