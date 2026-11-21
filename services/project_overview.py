"""Batch-read project progress without loading manuscripts or estimating runtime."""

import asyncio
from collections import defaultdict
import json
import math

from models.asset import Asset
from models.asset_variant import AssetVariant
from models.audio_reference import AudioReference
from models.chapter import Chapter
from models.novel import CLIP_AUTHOR, Novel
from models.remake_source import RemakeSource
from models.scene import Scene
from models.video import Video
from schemas.project_overview import (
    ClipOverview, ProjectOverview, ProjectOverviewItem, ProjectOverviewSummary, ProjectProduction, RemakeOverview,
)
from services.oss import normalize_media_url, resolve_media_url
from services.cover_derivatives import image_derivative_reference
from services.video.poster import video_media_url
from services.finished_episodes import completed_edit_rows
from services.audio_references import audio_reference_accessible
from utils.enums import TaskStatusEnum


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


_pending_overviews: dict[int | None, asyncio.Task[ProjectOverview]] = {}


async def project_overview(team_id: int | None = None) -> ProjectOverview:
    task = _pending_overviews.get(team_id)
    if task is None:
        task = asyncio.create_task(_load_project_overview(team_id))
        _pending_overviews[team_id] = task

        def finished(completed: asyncio.Task[ProjectOverview]) -> None:
            _pending_overviews.pop(team_id)
            if not completed.cancelled():
                completed.exception()  # Also observe failures if every HTTP caller disconnected.

        task.add_done_callback(finished)
    return await asyncio.shield(task)


async def _clip_overviews(projects) -> dict[int, ClipOverview]:
    ids = [p["id"] for p in projects if p["author"] == CLIP_AUTHOR]
    if not ids:
        return {}
    clips = {}
    for key, raw in await Novel.filter(id__in=ids).values_list("id", "project_setting"):
        try:
            settings = _mapping(json.loads(raw or "{}"))
        except ValueError:
            settings = {}
        kind = settings.get("task_type")
        if kind == "image" and settings.get("output_format") == "gif":
            kind = "gif"
        clips[key] = ClipOverview(kind=kind if kind in ("image", "gif", "video") else None,
                                  resolution=settings.get("resolution") if isinstance(settings.get("resolution"), str) else None)
    return clips


async def _load_project_overview(team_id: int | None) -> ProjectOverview:
    projects = await Novel.filter(**({"team_id": team_id} if team_id is not None else {})).values(
        "id", "name", "author", "description", "cover", "total_chapters", "workflow_kind",
        "aspect_ratio", "resolution", "tags", "project_type", "created_at", "updated_at",
        "narrator_audio_reference_id",
        "team_id", "created_by",
    )
    if not projects:
        return ProjectOverview(items=[], summary=ProjectOverviewSummary())
    clips = await _clip_overviews(projects)
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
    ready_chapters = set()

    def add_media(project_id, value):
        if isinstance(value, str) and value.strip():
            if reference := normalize_media_url(value.strip()):
                media[project_id].add(reference)

    def add_voice(project_id, value):
        if reference_id := _reference_id(value):
            voice_ids[project_id].add(reference_id)

    def touch(project_id, value):
        metrics[project_id].latest_activity_at = max(metrics[project_id].latest_activity_at, value)

    remakes = {p["id"]: RemakeOverview() for p in projects if p["workflow_kind"] == "remake"}
    if remakes:
        sources = await RemakeSource.filter(novel_id__in=list(remakes), chapter_id__in=[c["id"] for c in chapters]).values(
            "novel_id", "media_status", "updated_at", "analysis_task__status", "analysis_task__updated_at",
        )
        for source in sources:
            key = source["novel_id"]
            remake = remakes[key]
            remake.source_count += 1
            status = source["analysis_task__status"]
            if status == TaskStatusEnum.completed or (status is None and source["media_status"] == "completed"):
                remake.analyzed_count += 1
            touch(key, source["updated_at"])
            if source["analysis_task__updated_at"]:
                touch(key, source["analysis_task__updated_at"])

    asset_projects = {asset["id"]: asset["novel_id"] for asset in assets}
    for project in projects:
        add_voice(project["id"], project["narrator_audio_reference_id"])
    clip_images = {}
    for asset in assets:
        project_id = asset["novel_id"]
        if project_id in clips and asset["main_image"]:
            previous = clip_images.get(project_id)
            if previous is None or (asset["updated_at"], asset["id"]) > (previous["updated_at"], previous["id"]):
                clip_images[project_id] = asset
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
            if await audio_reference_accessible(voice, team_id=project["team_id"], created_by=project["created_by"]):
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
            clip = clips.get(project_id)
            if clip and clip.kind in (None, "video") and not clip.preview:
                meta = _mapping(selected["metadata"])
                if isinstance(poster := meta.get("poster_url"), str):
                    clip.preview = video_media_url(poster)
                if isinstance(thumbnail := meta.get("poster_thumbnail_url"), str):
                    clip.thumbnail = video_media_url(thumbnail)
            completed += 1
            metric.completed_shot_count += 1
            add_media(project_id, selected["url"])
            seconds = _reported_seconds(selected)
            if seconds is None:
                metric.unknown_duration_count += 1
            else:
                metric.video_seconds += seconds
            touch(project_id, selected["updated_at"])
        if shots and completed == len(shots):
            ready_chapters.add(chapter["id"])
    completed_chapters = set()
    chapter_numbers = {chapter["id"]: chapter["number"] for chapter in chapters}
    for row in await completed_edit_rows(chapter_projects):
        chapter_id = row['chapter_id']
        project_id = chapter_projects[chapter_id]
        if chapter_id in completed_chapters or row['novel_id'] != project_id:
            continue
        completed_chapters.add(chapter_id)
        metric = metrics[project_id]
        metric.completed_episode_count += 1
        value = _mapping(row['output_probe']).get('duration')
        try:
            seconds = float(value)
        except (ValueError, TypeError):
            seconds = float('nan')
        if math.isfinite(seconds) and seconds > 0:
            metric.finished_seconds += seconds
        else:
            metric.unknown_finished_duration_count += 1
        finished_at = row['completed_at'] or row['updated_at']
        touch(project_id, finished_at)
        if project_id not in latest_completion or finished_at > latest_completion[project_id]:
            latest_completion[project_id] = finished_at
            metric.latest_episode_number = chapter_numbers[chapter_id]
    for chapter_id in ready_chapters - completed_chapters:
        metrics[chapter_projects[chapter_id]].pending_composition_count += 1
    items = []
    for project in projects:
        metric = metrics[project["id"]]
        metric.asset_count = len(media[project["id"]])
        metric.video_seconds = round(metric.video_seconds, 3)
        metric.finished_seconds = round(metric.finished_seconds, 3)
        metric.state = "ready" if metric.completed_episode_count else "in_progress" if metric.shot_count or metric.asset_count else "not_started"
        remake = remakes.get(project["id"])
        if remake and remake.source_count and metric.state == "not_started":
            metric.state = "in_progress"
        clip = clips.get(project["id"])
        if clip:
            image = clip_images.get(project["id"])
            if clip.kind is None:
                clip.kind = "video" if metric.shot_count else "image" if image else None
            if clip.kind in ("image", "gif") and image:
                reference = normalize_media_url(image["main_image"])
                clip.preview = resolve_media_url(reference)
                clip.thumbnail = resolve_media_url(image_derivative_reference(reference, "thumbnail"))
                metric.state = "ready"
            elif clip.kind == "video" and metric.completed_shot_count:
                metric.state = "ready"
        items.append(ProjectOverviewItem.model_validate({
            **project, "tags": project["tags"] or [], "production": metric, "clip": clip, "remake": remake,
        }))
    items.sort(key=lambda item: (item.production.latest_activity_at, item.id), reverse=True)
    return ProjectOverview(items=items, summary=ProjectOverviewSummary(
        finished_seconds=round(sum(item.production.finished_seconds for item in items),3),
        unknown_finished_duration_count=sum(item.production.unknown_finished_duration_count for item in items),
        project_count=len(items), chapter_count=sum(item.production.chapter_count for item in items),
        asset_count=sum(item.production.asset_count for item in items),
        video_seconds=round(sum(item.production.video_seconds for item in items), 3),
        unknown_duration_count=sum(item.production.unknown_duration_count for item in items),
    ))
