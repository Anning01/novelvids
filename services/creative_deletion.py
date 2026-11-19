"""Permanent deletion initiated from the episode and asset management UI."""

import re

from fastapi import HTTPException
from tortoise.expressions import Q
from tortoise.timezone import now

from models.ai_task import AiTask
from models.agent_operation import AgentOperation
from models.agent_submission import AgentSubmission
from models.asset import Asset
from models.asset_variant import AssetVariant
from models.chapter import Chapter
from models.chapter_export import ChapterExport
from models.finished_episode import FinishedEpisodePublication
from models.novel import Novel
from models.portfolio import PortfolioWork
from models.remake_source import RemakeSource
from models.remake_upload import RemakeUpload
from models.resource_library import ResourcePlacement
from models.scene import Scene
from models.video import Video
from models.video_edit import ChapterCanvasSnapshot, ChapterEditDraft
from models.work_sync import WorkSyncObject
from services.creation_objects import ACTIVE_TASK_STATUSES, project_write
from services.deleted_media import MEDIA_FIELDS, enqueue_media
from services.extraction.context import normalize_source_chapters
from services.oss import oss
from services.reference.dependencies import REFERENCE_KEY
from services.task_cancellation import cancel_task
from services.video.asset_resolver import normalize_selected_variant_ids, variant_selection_ids
from services.video_editor.finished_media import cover_reference
from services.video_enhancement.media import export_media
from utils.messages import localized_message
from utils.enums import TaskStatusEnum


def _values(model, row):
    if model is RemakeSource:
        ref = f"/media/{row.object_key.removeprefix('/media/')}" if row.storage_provider == "local" else row.object_key
        return [ref]
    return [getattr(row, column) for column in MEDIA_FIELDS[model]]


async def _stop_tasks(tasks):
    for task in tasks:
        if task.status in ACTIVE_TASK_STATUSES:
            try:
                await cancel_task(task.id)
            except HTTPException as error:
                # Cancelling a parent can also stop a child in this list.
                if error.status_code != 400 or await AiTask.filter(id=task.id, status__in=ACTIVE_TASK_STATUSES).exists():
                    raise


def _chapter_task(params, chapter, scene_ids, video_ids, export_ids):
    return (
        params.get("chapter_id") == chapter.id
        or any(isinstance(params.get(key), int) and params[key] in ids
               for key, ids in (("scene_id", scene_ids), ("video_id", video_ids), ("export_id", export_ids)))
    )


def _video_is_committed(video):
    metadata = video.metadata or {}
    return metadata.get("billing_pending") or (
        video.status in ACTIVE_TASK_STATUSES and (video.external_task_id or metadata.get("submission_pending"))
    )


def _export_is_committed(export):
    return (export.provider_task_id or export.submission_slot) and not export.collection_complete


def _export_media_refs(exports):
    for row in exports:
        yield _values(ChapterExport, row)
        yield cover_reference(row.id)
        for kind in ("source", "edited", "enhanced"):
            yield export_media.ref(row, kind)
            yield f"/media/exports/{row.id}/{kind}.mp4"


async def _remove_exports(exports, team_id):
    if not exports:
        return
    if any(_export_is_committed(row) for row in exports):
        raise HTTPException(409, localized_message("视频任务已提交，完成处理后即可删除"))
    task_ids = [row.task_id for row in exports if row.task_id]
    if task_ids:
        await _stop_tasks(await AiTask.filter(id__in=task_ids))
        await AgentSubmission.filter(task_id__in=task_ids).delete()
    await enqueue_media(list(_export_media_refs(exports)), team_id)
    ids = [row.id for row in exports]
    await FinishedEpisodePublication.filter(export_id__in=ids).delete()
    await ChapterExport.filter(id__in=ids).delete()


async def delete_export(export_id, novel_id):
    async with project_write(novel_id):
        export = await ChapterExport.filter(id=export_id, novel_id=novel_id).select_for_update().get()
        applied = next((video for video in await Video.filter(scene__chapter_id=export.chapter_id)
            if (video.metadata or {}).get("enhancement_export_id") == export.id), None)
        if applied is not None:
            await delete_video(applied.id, novel_id)
        else:
            await _remove_exports([export], (await Novel.get(id=novel_id)).team_id)


async def delete_video(video_id, novel_id):
    async with project_write(novel_id):
        video = await Video.filter(id=video_id).select_for_update().get()
        scene = await Scene.with_deleted().filter(id=video.scene_id, chapter__novel_id=novel_id).get()
        if _video_is_committed(video):
            raise HTTPException(409, localized_message("视频任务已提交，完成处理后即可删除"))
        team_id = (await Novel.get(id=novel_id)).team_id
        origin_export = (video.metadata or {}).get("enhancement_export_id")
        exports = await ChapterExport.filter(
            Q(source_video_id=video.id) | Q(id=origin_export), novel_id=novel_id, chapter_id=scene.chapter_id,
        ).select_for_update()
        await _remove_exports(exports, team_id)
        tasks = [task for task in await AiTask.filter(status__in=ACTIVE_TASK_STATUSES)
                 if (task.request_params or {}).get("video_id") == video.id]
        await _stop_tasks(tasks)
        await enqueue_media(_values(Video, video), team_id, video_ids=[video.id])
        await video.delete()
        metadata = dict(scene.metadata or {})
        workbench = dict(metadata.get("workbench") or {})
        selected = metadata.get("current_video_id") or workbench.get("activeVideoId")
        if selected == video_id or workbench.get("activeVideoId") == video_id:
            workbench.pop("activeVideoId", None)
            if selected == video_id:
                replacement = await Video.filter(
                    scene_id=scene.id, status=TaskStatusEnum.completed.value, url__isnull=False,
                ).exclude(url="").order_by("-id").first()
                metadata.pop("current_video_id", None)
                if replacement:
                    metadata["current_video_id"] = replacement.id
            if "workbench" in metadata:
                metadata["workbench"] = workbench
            await Scene.with_deleted().filter(id=scene.id).update(metadata=metadata, updated_at=now())


async def composition_tasks(chapter_id):
    return [task for task in await AiTask.filter(task_type=4).order_by("-created_at")
            if task.request_params.get("operation") == "compose" and task.request_params.get("chapter_id") == chapter_id]


def composition_paths(chapter_id, team_id):
    filename = f"videos/merged/chapter_{chapter_id}_merged.mp4"
    return [f"/media/{filename}", *([f"uploads/{team_id or 0}/{filename}"] if oss.enabled else [])]


async def delete_composition(chapter_id, novel_id):
    async with project_write(novel_id):
        await Chapter.get(id=chapter_id, novel_id=novel_id)
        team_id = (await Novel.get(id=novel_id)).team_id
        tasks = await composition_tasks(chapter_id)
        if any(task.status == TaskStatusEnum.running.value for task in tasks):
            raise HTTPException(409, localized_message("视频任务已提交，完成处理后即可删除"))
        await _stop_tasks(tasks)
        media = composition_paths(chapter_id, team_id)
        ids = [task.id for task in tasks]
        receipts = await AgentOperation.filter(task_id__in=ids, key="media:compose").values_list("result", flat=True)
        media.extend(receipts)
        for task in tasks:
            result = task.response_data or {}
            media.extend(result.get(key) for key in ("merged_url", "poster_url", "poster_thumbnail_url"))
            await AiTask.filter(id=task.id).update(response_data=None,
                request_params={**task.request_params, "composition_deleted": True})
        await AgentSubmission.filter(task_id__in=ids).delete()
        await AgentOperation.filter(task_id__in=ids, key="media:compose").update(result={})
        canvas = await ChapterCanvasSnapshot.get_or_none(chapter_id=chapter_id)
        if canvas:
            layout = canvas.layout or {}
            for node in layout.get("manualNodes", []):
                if node.get("kind") == "video_composer":
                    node.get("data", {}).pop("result", None)
            await ChapterCanvasSnapshot.filter(id=canvas.id).update(layout=layout, updated_at=now())
        await enqueue_media(media, team_id)


async def delete_chapter(chapter_id, novel_id):
    async with project_write(novel_id):
        chapter = await Chapter.get(id=chapter_id, novel_id=novel_id)
        project = await Novel.get(id=novel_id)
        scenes = await Scene.with_deleted().filter(chapter_id=chapter_id)
        videos = await Video.filter(scene__chapter_id=chapter_id)
        exports = await ChapterExport.filter(chapter_id=chapter_id, novel_id=novel_id).select_for_update()
        # Accepted provider jobs still need their records to finish settlement.
        if any(map(_video_is_committed, videos)) or any(map(_export_is_committed, exports)):
            raise HTTPException(409, localized_message("本集有已提交的生成任务，请等待处理完成后再永久删除"))
        models = {Scene: scenes, Video: videos,
                  RemakeSource: await RemakeSource.filter(chapter_id=chapter_id),
                  ChapterCanvasSnapshot: await ChapterCanvasSnapshot.filter(chapter_id=chapter_id),
                  ChapterEditDraft: await ChapterEditDraft.filter(chapter_id=chapter_id)}
        scene_ids = {row.id for row in scenes}
        video_ids = {row.id for row in videos}
        export_ids = {row.id for row in exports}
        task_ids = {row.task_id for row in exports}
        tasks = [task for task in await AiTask.all()
                 if task.id in task_ids or _chapter_task(task.request_params or {}, chapter, scene_ids, video_ids, export_ids)]
        await _stop_tasks(tasks)

        for task in tasks:
            if task.request_params.get("operation") == "compose":
                result = (await AiTask.get(id=task.id)).response_data or {}
                await enqueue_media([result.get(key) for key in ("merged_url", "poster_url", "poster_thumbnail_url")], project.team_id)
                await AiTask.filter(id=task.id).update(response_data=None)
                await AgentOperation.filter(task=task, key="media:compose").update(result={})
        await enqueue_media([
            *[_values(model, row) for model, rows in models.items() for row in rows],
            *composition_paths(chapter_id, project.team_id),
        ], project.team_id, video_ids=video_ids)
        await _remove_exports(exports, project.team_id)
        await RemakeUpload.filter(team_id=project.team_id, status="committed",
            object_key__in=[row.object_key for row in models[RemakeSource]]).delete()
        await PortfolioWork.filter(novel_id=novel_id, cover_chapter_id=chapter_id).update(cover_chapter_id=None)
        await WorkSyncObject.filter(kind="episode", local_id=chapter_id).delete()
        await WorkSyncObject.filter(kind="shot", local_id__in=scene_ids).delete()
        await chapter.delete()
        await _remove_chapter_assets(chapter, project.team_id)
        await Novel.filter(id=novel_id).update(episodes_managed=True,
            total_chapters=await Chapter.filter(novel_id=novel_id).count())


async def _remove_chapter_assets(chapter, team_id):
    assets = await Asset.filter(novel_id=chapter.novel_id)
    variants = await AssetVariant.filter(asset__novel_id=chapter.novel_id)
    referenced = {
        ref["asset_id"] for row in [*assets, *variants] for ref in (row.metadata or {}).get(REFERENCE_KEY, [])
        if isinstance(ref, dict) and isinstance(ref.get("asset_id"), int)
        and ref["asset_id"] != (row.asset_id if isinstance(row, AssetVariant) else row.id)
    }
    for asset in assets:
        chapters = normalize_source_chapters(asset.source_chapters)
        if chapter.number not in chapters:
            continue
        remaining = [number for number in chapters if number != chapter.number]
        if (not remaining and not asset.is_global and asset.id not in referenced
                and not await Scene.with_deleted().filter(assets__id=asset.id).exists()):
            forms = await AssetVariant.with_deleted().filter(asset_id=asset.id)
            await _delete_asset(asset, None, forms, team_id)
        else:
            await Asset.filter(id=asset.id).update(source_chapters=remaining,
                last_updated_chapter=max(remaining, default=0), updated_at=now())
    for variant in variants:
        numbers = normalize_source_chapters(variant.chapter_numbers)
        if chapter.number in numbers:
            await AssetVariant.filter(id=variant.id).update(
                chapter_numbers=[n for n in numbers if n != chapter.number], updated_at=now())


async def _mention_pattern(asset, variant):
    names = {asset.canonical_name, *(asset.aliases or [])} - {""}
    for name, aliases in await Asset.filter(novel_id=asset.novel_id).exclude(id=asset.id).values_list("canonical_name", "aliases"):
        names.difference_update([name, *(aliases or [])])
    suffix = "#" + re.escape(variant.name) if variant else r"(?:#[^}]+)?"
    return re.compile(r"@\{(?:" + "|".join(re.escape(name) for name in sorted(names)) + ")" + suffix + r"\}") if names else None


def _strip_mentions(value, pattern):
    if pattern is None:
        return value
    if isinstance(value, str):
        return pattern.sub("", value)
    if isinstance(value, list):
        return [_strip_mentions(item, pattern) for item in value]
    if isinstance(value, dict):
        return {key: _strip_mentions(item, pattern) for key, item in value.items()}
    return value


def _scene_changes(scene, asset, variant, mention):
    metadata = dict(scene.metadata or {})
    if isinstance(metadata.get("asset_variant_ids"), dict):
        bindings = dict(metadata["asset_variant_ids"])
        asset_key = str(asset.id)
        if asset_key in bindings:
            if variant is None:
                bindings.pop(asset_key)
            else:
                selection = normalize_selected_variant_ids({asset_key: bindings[asset_key]})
                selected = variant_selection_ids(selection[asset.id]) if asset.id in selection else []
                remaining = [item for item in selected if item != variant.id]
                if len(remaining) != len(selected):
                    bindings[asset_key] = remaining or [None]
            metadata["asset_variant_ids"] = bindings
    if variant is None and isinstance(metadata.get("voice_asset_ids"), list):
        metadata["voice_asset_ids"] = [item for item in metadata["voice_asset_ids"] if item != asset.id]
    values = {"metadata": metadata, "prompt": _strip_mentions(scene.prompt, mention),
              "description": _strip_mentions(scene.description, mention),
              "prompt_params": _strip_mentions(scene.prompt_params, mention)}
    return {key: value for key, value in values.items() if value != getattr(scene, key)}


async def affected_asset_scenes(asset, variant=None):
    mention = await _mention_pattern(asset, variant)
    scenes = await Scene.filter(chapter__novel_id=asset.novel_id).order_by("chapter__number", "sequence").select_related("chapter")
    linked = set() if variant else set(await Scene.filter(assets__id=asset.id).values_list("id", flat=True))
    return [{"chapter_number": scene.chapter.number, "sequence": scene.sequence}
            for scene in scenes if scene.id in linked or _scene_changes(scene, asset, variant, mention)]


async def delete_asset(asset_id, novel_id, variant_id=None):
    async with project_write(novel_id):
        asset = await Asset.get(id=asset_id, novel_id=novel_id)
        variant = await AssetVariant.get_or_none(id=variant_id, asset_id=asset_id)
        if variant_id is not None and variant is None:
            raise HTTPException(404, localized_message("资产形态不存在"))
        variants = [variant] if variant else await AssetVariant.with_deleted().filter(asset_id=asset.id)
        await _delete_asset(asset, variant, variants, (await Novel.get(id=novel_id)).team_id)


async def _delete_asset(asset, variant, variants, team_id):
    tasks = [task for task in await AiTask.all() if (task.request_params or {}).get("asset_id") == asset.id
             and (variant is None or task.request_params.get("variant_id") == variant.id)]
    await _stop_tasks(tasks)
    media = [_values(AssetVariant, row) for row in variants]
    if variant is None:
        media.append(_values(Asset, asset))
    for task in tasks:
        # Retain the task identity and usage records, but remove its generated image history.
        result = dict((await AiTask.get(id=task.id)).response_data or {})
        images = result.pop("images", [])
        if images:
            media.append(images)
            await AiTask.filter(id=task.id).update(response_data=result)

    mention = await _mention_pattern(asset, variant)
    for scene in await Scene.with_deleted().filter(chapter__novel_id=asset.novel_id):
        if changes := _scene_changes(scene, asset, variant, mention):
            await Scene.with_deleted().filter(id=scene.id).update(**changes, updated_at=now())
    for model, scope in ((Asset, {"novel_id": asset.novel_id}), (AssetVariant, {"asset__novel_id": asset.novel_id})):
        for row in await model.with_deleted().filter(**scope):
            metadata = row.metadata or {}
            refs = metadata.get(REFERENCE_KEY, [])
            remaining = [ref for ref in refs if not (
                isinstance(ref, dict) and ref.get("asset_id") == asset.id
                and (variant is None or ref.get("variant_id") == variant.id)
            )]
            if remaining != refs:
                await model.with_deleted().filter(id=row.id).update(
                    metadata={**metadata, REFERENCE_KEY: remaining}, updated_at=now())

    await enqueue_media(media, team_id, asset_id=asset.id)
    await WorkSyncObject.filter(kind="variant", local_id__in=[row.id for row in variants]).delete()
    if variant:
        await variant.delete()
    else:
        await WorkSyncObject.filter(kind="asset", local_id=asset.id).delete()
        await ResourcePlacement.filter(catalog="asset", source_id=asset.id).delete()
        await asset.delete()
